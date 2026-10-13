"""Focus session lifecycle: start -> (pause <-> resume)* -> stop.

Every transition is recorded as a SessionEvent, cache-invalidated, and pushed to the user's live clients.
"""

from datetime import date, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.events import publish_user_event
from app.core.timeutils import ensure_utc, is_in_future, local_range_to_utc, local_today, now_utc, period_bounds
from app.models.distraction_event import DistractionEvent
from app.models.focus_session import FocusSession, SessionStatus
from app.models.session_event import SessionEvent, SessionEventType
from app.models.user import User
from app.schemas.session import (
    SessionDetailResponse,
    SessionResponse,
    SessionUpdateRequest,
    TimelineItem,
)
from app.services.activity import close_open_segment
from app.services.analytics import invalidate_productivity_cache
from app.services.focus import compute_focus_score, live_focus_seconds
from app.services.tag import get_owned_tag
from app.services.user_settings import get_user_settings

# ---------------------------------------------------------------------------
# Queries and response building
# ---------------------------------------------------------------------------


def get_active_session(db: Session, user: User) -> FocusSession | None:
    """The user's unfinished session (active or paused), if any."""
    return db.scalar(select(FocusSession).where(FocusSession.user_id == user.id, FocusSession.end_time.is_(None)))


def get_owned_session(db: Session, user: User, session_id: int) -> FocusSession:
    session = db.get(FocusSession, session_id)
    if session is None or session.user_id != user.id:
        raise NotFoundError("Session not found")
    return session


def distraction_counts(db: Session, session_ids: list[int]) -> dict[int, int]:
    if not session_ids:
        return {}
    rows = db.execute(
        select(DistractionEvent.session_id, func.count(DistractionEvent.id))
        .where(DistractionEvent.session_id.in_(session_ids))
        .group_by(DistractionEvent.session_id)
    ).all()
    return dict(rows)


def _current_paused_seconds(session: FocusSession, now: datetime) -> int:
    paused = session.paused_seconds
    if session.status == SessionStatus.PAUSED and session.paused_at is not None:
        paused += max(0, int((now - ensure_utc(session.paused_at)).total_seconds()))
    return paused


def build_response(session: FocusSession, distraction_count: int, now: datetime | None = None) -> SessionResponse:
    now = now or now_utc()
    focus_seconds = live_focus_seconds(session, now)
    if session.status == SessionStatus.ENDED and session.focus_score is not None:
        score = session.focus_score
    else:
        score = compute_focus_score(focus_seconds, _current_paused_seconds(session, now), distraction_count)
    return SessionResponse(
        id=session.id,
        user_id=session.user_id,
        tag_id=session.tag_id,
        intent=session.intent,
        status=session.status,
        start_time=session.start_time,
        end_time=session.end_time,
        paused_at=session.paused_at,
        paused_seconds=session.paused_seconds,
        duration_seconds=focus_seconds,
        distraction_count=distraction_count,
        focus_score=score,
        pause_threshold_seconds=session.pause_threshold_seconds,
    )


def session_response(db: Session, session: FocusSession) -> SessionResponse:
    return build_response(session, distraction_counts(db, [session.id]).get(session.id, 0))


def _publish(db: Session, user: User, session: FocusSession) -> SessionResponse:
    response = session_response(db, session)
    publish_user_event(user.id, "session.updated", {"session": response.model_dump(mode="json")})
    return response


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------


def _resolve_at(at: datetime | None) -> datetime:
    resolved = ensure_utc(at) if at else now_utc()
    if is_in_future(resolved):
        raise BadRequestError("Time cannot be in the future")
    return resolved


def _last_event_time(db: Session, session: FocusSession) -> datetime:
    last = db.scalar(select(func.max(SessionEvent.timestamp)).where(SessionEvent.session_id == session.id))
    return ensure_utc(last) if last else ensure_utc(session.start_time)


def _require_after_last_event(db: Session, session: FocusSession, at: datetime) -> None:
    if at < _last_event_time(db, session):
        raise BadRequestError("Time cannot be earlier than the session's previous event")


def _add_event(db: Session, session: FocusSession, event_type: SessionEventType, at: datetime, details=None) -> None:
    db.add(SessionEvent(session=session, event_type=event_type, timestamp=at, details=details))


def _finish(db: Session, session: FocusSession, end: datetime, details: dict | None = None) -> None:
    """Close an open session at `end` (which, for a paused session, must be its pause start or later)."""
    if session.status == SessionStatus.PAUSED:
        # Time paused up to `end` counts as pause, not focus.
        session.paused_seconds += max(0, int((end - ensure_utc(session.paused_at)).total_seconds()))
        session.paused_at = None
    session.status = SessionStatus.ENDED
    session.end_time = end
    session.duration_seconds = max(
        0, int((end - ensure_utc(session.start_time)).total_seconds()) - session.paused_seconds
    )
    _add_event(db, session, SessionEventType.STOPPED, end, details)
    close_open_segment(db, session.user_id, end)
    db.flush()
    refresh_focus_score(db, session)


def refresh_focus_score(db: Session, session: FocusSession) -> None:
    """Recompute the stored score of an ended session (e.g. after a distraction is logged against it)."""
    if session.status != SessionStatus.ENDED:
        return
    count = distraction_counts(db, [session.id]).get(session.id, 0)
    session.focus_score = compute_focus_score(session.duration_seconds, session.paused_seconds, count)


def start_session(
    db: Session, user: User, tag_id: int | None = None, intent: str | None = None, start_time: datetime | None = None
) -> SessionResponse:
    if get_active_session(db, user):
        raise ConflictError("You already have an active session")
    if tag_id is not None:
        get_owned_tag(db, user, tag_id)
    start = _resolve_at(start_time)

    session = FocusSession(
        user_id=user.id,
        tag_id=tag_id,
        intent=intent,
        status=SessionStatus.ACTIVE,
        start_time=start,
        pause_threshold_seconds=get_user_settings(db, user).pause_threshold_seconds,
    )
    db.add(session)
    _add_event(db, session, SessionEventType.STARTED, start)
    try:
        db.commit()
    except IntegrityError as exc:  # lost a race with another start request
        db.rollback()
        raise ConflictError("You already have an active session") from exc
    invalidate_productivity_cache(user.id)
    return _publish(db, user, session)


def _require_open_session(db: Session, user: User) -> FocusSession:
    session = get_active_session(db, user)
    if session is None:
        raise NotFoundError("No active session found")
    return session


def pause_session(db: Session, user: User, at: datetime | None = None) -> SessionResponse:
    session = _require_open_session(db, user)
    if session.status == SessionStatus.PAUSED:
        raise ConflictError("Session is already paused")
    paused = _resolve_at(at)
    _require_after_last_event(db, session, paused)

    session.status = SessionStatus.PAUSED
    session.paused_at = paused
    close_open_segment(db, user.id, paused)  # time on a break isn't time on a window
    _add_event(db, session, SessionEventType.PAUSED, paused)
    db.commit()
    invalidate_productivity_cache(user.id)
    return _publish(db, user, session)


def resume_session(
    db: Session, user: User, at: datetime | None = None
) -> tuple[SessionResponse, SessionResponse | None]:
    """Resume a paused session. A pause longer than the session's threshold ends it at the pause start
    and starts a fresh session instead; then the closed session is returned as the second value."""
    session = _require_open_session(db, user)
    if session.status != SessionStatus.PAUSED:
        raise ConflictError("Session is not paused")
    resumed = _resolve_at(at)
    paused_at = ensure_utc(session.paused_at)
    if resumed < paused_at:
        raise BadRequestError("Cannot resume before the pause started")

    pause_seconds = int((resumed - paused_at).total_seconds())
    if pause_seconds <= session.pause_threshold_seconds:
        session.paused_seconds += pause_seconds
        session.paused_at = None
        session.status = SessionStatus.ACTIVE
        _add_event(db, session, SessionEventType.RESUMED, resumed, {"pause_seconds": pause_seconds})
        db.commit()
        invalidate_productivity_cache(user.id)
        return _publish(db, user, session), None

    # Long break: the old session ends where the pause began, so the break is not counted at all.
    session.paused_at = None
    session.status = SessionStatus.ACTIVE
    _finish(db, session, paused_at, {"reason": "long_pause", "pause_seconds": pause_seconds})

    new_session = FocusSession(
        user_id=user.id,
        tag_id=session.tag_id,
        intent=session.intent,
        status=SessionStatus.ACTIVE,
        start_time=resumed,
        pause_threshold_seconds=session.pause_threshold_seconds,
    )
    db.add(new_session)
    db.flush()
    _add_event(db, new_session, SessionEventType.STARTED, resumed, {"split_from": session.id})
    db.commit()
    invalidate_productivity_cache(user.id)
    previous = _publish(db, user, session)
    return _publish(db, user, new_session), previous


def stop_session(db: Session, user: User, at: datetime | None = None) -> SessionResponse:
    session = _require_open_session(db, user)
    end = _resolve_at(at)
    _require_after_last_event(db, session, end)
    _finish(db, session, end)
    db.commit()
    invalidate_productivity_cache(user.id)
    return _publish(db, user, session)


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def update_session(db: Session, user: User, session_id: int, payload: SessionUpdateRequest) -> SessionResponse:
    session = get_owned_session(db, user, session_id)
    if "tag_id" in payload.model_fields_set:
        if payload.tag_id is not None:
            get_owned_tag(db, user, payload.tag_id)
        session.tag_id = payload.tag_id
    if "intent" in payload.model_fields_set:
        session.intent = payload.intent
    db.commit()
    invalidate_productivity_cache(user.id)
    return _publish(db, user, session)


def delete_session(db: Session, user: User, session_id: int) -> None:
    """Delete a session together with its distractions (they belong to it) and history."""
    session = get_owned_session(db, user, session_id)
    db.execute(delete(DistractionEvent).where(DistractionEvent.session_id == session.id))
    db.delete(session)
    db.commit()
    invalidate_productivity_cache(user.id)
    publish_user_event(user.id, "session.deleted", {"session_id": session_id})


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def get_session_detail(db: Session, user: User, session_id: int) -> SessionDetailResponse:
    session = get_owned_session(db, user, session_id)
    distractions = list(db.scalars(select(DistractionEvent).where(DistractionEvent.session_id == session.id)))
    timeline = [
        TimelineItem(kind=event.event_type.value, timestamp=event.timestamp, details=event.details)
        for event in session.events
    ] + [
        TimelineItem(
            kind="distraction",
            timestamp=d.timestamp,
            details={"id": d.id, "type": d.event_type.value, "reason": d.reason},
        )
        for d in distractions
    ]
    # Stable order: by time, with lifecycle events before distractions at the same instant.
    timeline.sort(key=lambda item: (ensure_utc(item.timestamp), item.kind == "distraction"))
    base = build_response(session, len(distractions))
    return SessionDetailResponse(**base.model_dump(), timeline=timeline)


def resolve_date_range(
    user: User, period: str, reference_date: date | None, start_date: date | None, end_date: date | None
) -> tuple[date, date]:
    if period == "custom":
        if not start_date or not end_date:
            raise BadRequestError("custom range requires start_date and end_date")
        if end_date < start_date:
            raise BadRequestError("end_date must be >= start_date")
        return start_date, end_date
    return period_bounds(period, reference_date or local_today(user.timezone))


def list_sessions(
    db: Session, user: User, period: str, reference_date: date | None, start_date: date | None, end_date: date | None
) -> tuple[list[SessionResponse], int]:
    first_day, last_day = resolve_date_range(user, period, reference_date, start_date, end_date)
    range_start, range_end = local_range_to_utc(first_day, last_day, user.timezone)

    sessions = list(
        db.scalars(
            select(FocusSession)
            .where(
                FocusSession.user_id == user.id,
                FocusSession.start_time >= range_start,
                FocusSession.start_time < range_end,
            )
            .order_by(FocusSession.start_time.desc())
        )
    )
    counts = distraction_counts(db, [s.id for s in sessions])
    now = now_utc()
    responses = [build_response(s, counts.get(s.id, 0), now) for s in sessions]
    return responses, sum(r.duration_seconds for r in responses)
