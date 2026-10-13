from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.events import publish_user_event
from app.core.timeutils import ensure_utc, is_in_future, local_range_to_utc, now_utc
from app.models.activity import ActivityRule, RuleKind
from app.models.distraction_event import DistractionEvent, DistractionType
from app.models.focus_session import FocusSession
from app.models.user import User
from app.schemas.distraction import DistractionResponse
from app.services.activity import set_rule
from app.services.analytics import invalidate_productivity_cache
from app.services.session import get_active_session, refresh_focus_score, session_response


def _resolve_timestamp(ts: datetime | None) -> datetime:
    resolved = ensure_utc(ts) if ts else now_utc()
    if is_in_future(resolved):
        raise BadRequestError("timestamp cannot be in the future")
    return resolved


def _resolve_session(db: Session, user: User, session_id: int | None, timestamp: datetime) -> FocusSession | None:
    """The session a distraction belongs to: the one given, or else the running session if it covers `timestamp`."""
    if session_id is None:
        active = get_active_session(db, user)
        if active is not None and timestamp >= ensure_utc(active.start_time):
            return active
        return None

    session = db.get(FocusSession, session_id)
    if not session or session.user_id != user.id:
        raise NotFoundError("Session not found")
    starts = ensure_utc(session.start_time)
    ends = ensure_utc(session.end_time) if session.end_time else None
    if timestamp < starts or (ends is not None and timestamp > ends):
        raise BadRequestError("timestamp is outside the session's time range")
    return session


def _log(
    db: Session,
    user: User,
    event_type: DistractionType,
    session_id: int | None,
    reason: str | None,
    timestamp: datetime | None,
    inactive_minutes: int | None = None,
    subject: str | None = None,
) -> DistractionEvent:
    resolved = _resolve_timestamp(timestamp)
    session = _resolve_session(db, user, session_id, resolved)
    event = DistractionEvent(
        user_id=user.id,
        session_id=session.id if session else None,
        event_type=event_type,
        reason=reason,
        subject=subject,
        inactive_minutes=inactive_minutes,
        timestamp=resolved,
    )
    db.add(event)
    db.flush()
    if session is not None:
        refresh_focus_score(db, session)  # no-op for open sessions; their score is computed live
    db.commit()
    invalidate_productivity_cache(user.id)

    publish_user_event(user.id, "distraction.logged", {"distraction": _payload(event)})
    _publish_session(db, user, session)
    return event


def _payload(event: DistractionEvent) -> dict:
    return DistractionResponse.model_validate(event).model_dump(mode="json")


def _publish_session(db: Session, user: User, session: FocusSession | None) -> None:
    if session is not None:
        publish_user_event(
            user.id, "session.updated", {"session": session_response(db, session).model_dump(mode="json")}
        )


def get_owned_distraction(db: Session, user: User, distraction_id: int) -> DistractionEvent:
    event = db.get(DistractionEvent, distraction_id)
    if event is None or event.user_id != user.id:
        raise NotFoundError("Distraction not found")
    return event


def log_detected_distraction(
    db: Session, user: User, source: DistractionType, subject: str, reason: str | None, timestamp: datetime | None
) -> DistractionEvent:
    """A distraction noticed by the desktop app (screen or camera), attached to the running session."""
    if source not in (DistractionType.SCREEN, DistractionType.CAMERA):
        raise BadRequestError("source must be screen or camera")
    if get_active_session(db, user) is None:
        raise ConflictError("No active session to attach the distraction to")
    return _log(db, user, source, None, reason or subject, timestamp, subject=subject)


def end_distraction(db: Session, user: User, distraction_id: int, at: datetime | None) -> DistractionEvent:
    """Record that the user is back on task: sets how long the distraction lasted."""
    event = get_owned_distraction(db, user, distraction_id)
    end = _resolve_timestamp(at)
    event.duration_seconds = max(0, int((end - ensure_utc(event.timestamp)).total_seconds()))
    db.commit()
    invalidate_productivity_cache(user.id)
    publish_user_event(user.id, "distraction.updated", {"distraction": _payload(event)})
    return event


def dismiss_distraction(db: Session, user: User, distraction_id: int, always_allow: bool) -> ActivityRule | None:
    """Remove a false alarm. With `always_allow`, also add a rule so the same subject is never flagged again."""
    event = get_owned_distraction(db, user, distraction_id)
    rule = None
    if always_allow:
        # Rules describe on-screen apps/sites, so only screen distractions can become one.
        if event.event_type != DistractionType.SCREEN or not event.subject:
            raise BadRequestError("Only screen distractions can be always allowed")
        rule = set_rule(db, user, event.subject.strip().lower()[:120], RuleKind.FOCUS)

    session = db.get(FocusSession, event.session_id) if event.session_id else None
    db.delete(event)
    db.flush()
    if session is not None:
        refresh_focus_score(db, session)
    db.commit()
    invalidate_productivity_cache(user.id)

    publish_user_event(user.id, "distraction.dismissed", {"distraction_id": distraction_id})
    _publish_session(db, user, session)
    return rule


def log_manual_distraction(
    db: Session, user: User, session_id: int | None, reason: str | None, timestamp: datetime | None
) -> DistractionEvent:
    return _log(db, user, DistractionType.MANUAL, session_id, reason, timestamp)


def log_inferred_distraction(
    db: Session,
    user: User,
    session_id: int | None,
    inactive_minutes: int,
    reason: str | None,
    timestamp: datetime | None,
) -> DistractionEvent:
    final_reason = reason or f"Inactive for {inactive_minutes} minutes"
    return _log(db, user, DistractionType.INFERRED, session_id, final_reason, timestamp, inactive_minutes)


def list_distractions(
    db: Session, user: User, day: date | None, limit: int, offset: int
) -> tuple[list[DistractionEvent], int]:
    filters = [DistractionEvent.user_id == user.id]
    if day:
        start, end = local_range_to_utc(day, day, user.timezone)
        filters += [DistractionEvent.timestamp >= start, DistractionEvent.timestamp < end]

    items = db.scalars(
        select(DistractionEvent)
        .where(*filters)
        .order_by(DistractionEvent.timestamp.desc(), DistractionEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    total = db.scalar(select(func.count(DistractionEvent.id)).where(*filters)) or 0
    return list(items), total


def get_daily_summary(db: Session, user: User, day: date) -> dict[DistractionType, int]:
    """Number of distractions of each type on a local day (every type present, zero if none)."""
    start, end = local_range_to_utc(day, day, user.timezone)
    rows = db.execute(
        select(DistractionEvent.event_type, func.count(DistractionEvent.id))
        .where(
            DistractionEvent.user_id == user.id, DistractionEvent.timestamp >= start, DistractionEvent.timestamp < end
        )
        .group_by(DistractionEvent.event_type)
    ).all()
    counts = dict(rows)
    return {kind: counts.get(kind, 0) for kind in DistractionType}
