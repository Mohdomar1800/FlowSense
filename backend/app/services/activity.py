"""Screen activity: classify foreground windows, record time per window, and manage the user's rules."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError
from app.core.events import publish_user_event
from app.core.timeutils import ensure_utc, is_in_future, now_utc
from app.models.activity import ActivityRule, ActivitySegment, RuleKind
from app.models.focus_session import FocusSession, SessionStatus
from app.models.user import User
from app.schemas.activity import ActivityResult
from app.services.classifier import UserRule, classify, page_title

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def list_rules(db: Session, user: User) -> list[ActivityRule]:
    return list(db.scalars(select(ActivityRule).where(ActivityRule.user_id == user.id).order_by(ActivityRule.pattern)))


def create_rule(db: Session, user: User, pattern: str, kind: RuleKind) -> ActivityRule:
    if db.scalar(select(ActivityRule.id).where(ActivityRule.user_id == user.id, ActivityRule.pattern == pattern)):
        raise ConflictError("A rule for this text already exists")
    rule = ActivityRule(user_id=user.id, pattern=pattern, kind=kind)
    db.add(rule)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A rule for this text already exists") from exc
    db.refresh(rule)
    return rule


def set_rule(db: Session, user: User, pattern: str, kind: RuleKind) -> ActivityRule:
    """Create or overwrite the rule for `pattern` (used by "always allow"). Does not commit."""
    rule = db.scalar(select(ActivityRule).where(ActivityRule.user_id == user.id, ActivityRule.pattern == pattern))
    if rule is None:
        rule = ActivityRule(user_id=user.id, pattern=pattern, kind=kind)
        db.add(rule)
    else:
        rule.kind = kind
    return rule


def delete_rule(db: Session, user: User, rule_id: int) -> None:
    rule = db.get(ActivityRule, rule_id)
    if rule is None or rule.user_id != user.id:
        raise NotFoundError("Rule not found")
    db.delete(rule)
    db.commit()


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def close_open_segment(db: Session, user_id: int, at: datetime) -> None:
    """End the user's current activity segment, if any. Does not commit."""
    segment = db.scalar(
        select(ActivitySegment).where(ActivitySegment.user_id == user_id, ActivitySegment.ended_at.is_(None))
    )
    if segment is None:
        return
    started = ensure_utc(segment.started_at)
    end = max(ensure_utc(at), started)  # reports can arrive slightly out of order
    segment.ended_at = end
    segment.duration_seconds = int((end - started).total_seconds())
    db.flush()


def record_activity(db: Session, user: User, app: str, title: str, at: datetime | None = None) -> ActivityResult:
    """Classify the window the user switched to and, during an active session, record it."""
    when = ensure_utc(at) if at else now_utc()
    if is_in_future(when):
        when = now_utc()

    session = db.scalar(
        select(FocusSession).where(FocusSession.user_id == user.id, FocusSession.status == SessionStatus.ACTIVE)
    )
    rules = [UserRule(rule.pattern, rule.kind.value) for rule in list_rules(db, user)]
    result = classify(app, title, intent=session.intent if session else None, rules=rules)

    close_open_segment(db, user.id, when)
    tracked = session is not None
    if tracked:
        db.add(
            ActivitySegment(
                user_id=user.id,
                session_id=session.id,
                app=app[:120],
                title=title[:300],
                subject=result.subject[:120],
                category=result.category,
                started_at=when,
            )
        )
    db.commit()

    activity = ActivityResult(category=result.category, subject=result.subject, reason=result.reason, tracked=tracked)
    publish_user_event(
        user.id,
        "activity.updated",
        {"activity": {**activity.model_dump(mode="json"), "title": page_title(app, title)[:200], "app": app[:120]}},
    )
    return activity
