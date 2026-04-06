from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models.distraction_event import DistractionEvent, DistractionType
from app.models.focus_session import FocusSession
from app.services.analytics import invalidate_productivity_cache


def _resolve_timestamp(ts: datetime | None) -> datetime:
    if ts is None:
        return datetime.now(UTC)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


def _validate_session_ownership(db: Session, user_id: int, session_id: int | None) -> None:
    if session_id is None:
        return
    session = db.get(FocusSession, session_id)
    if not session or session.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")


def log_manual_distraction(
    db: Session, user_id: int, session_id: int | None, reason: str | None, timestamp: datetime | None
) -> DistractionEvent:
    _validate_session_ownership(db, user_id, session_id)
    event = DistractionEvent(
        user_id=user_id,
        session_id=session_id,
        event_type=DistractionType.MANUAL,
        reason=reason,
        timestamp=_resolve_timestamp(timestamp),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    invalidate_productivity_cache(user_id)
    return event


def log_inferred_distraction(
    db: Session,
    user_id: int,
    session_id: int | None,
    inactive_minutes: int,
    reason: str | None,
    timestamp: datetime | None,
) -> DistractionEvent:
    _validate_session_ownership(db, user_id, session_id)
    final_reason = reason or f"Inferred after {inactive_minutes} minutes inactivity"
    event = DistractionEvent(
        user_id=user_id,
        session_id=session_id,
        event_type=DistractionType.INFERRED,
        reason=final_reason,
        timestamp=_resolve_timestamp(timestamp),
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    invalidate_productivity_cache(user_id)
    return event


def list_distractions(db: Session, user_id: int, day: date | None, limit: int, offset: int) -> tuple[list[DistractionEvent], int]:
    filters = [DistractionEvent.user_id == user_id]

    if day:
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        filters.append(and_(DistractionEvent.timestamp >= start, DistractionEvent.timestamp < end))

    items_stmt = (
        select(DistractionEvent)
        .where(and_(*filters))
        .order_by(DistractionEvent.timestamp.desc())
        .limit(limit)
        .offset(offset)
    )
    count_stmt = select(func.count(DistractionEvent.id)).where(and_(*filters))

    items = list(db.scalars(items_stmt).all())
    total_count = db.scalar(count_stmt) or 0
    return items, total_count


def get_daily_summary(db: Session, user_id: int, day: date) -> tuple[int, int, int]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    end = start + timedelta(days=1)

    base_filter = and_(
        DistractionEvent.user_id == user_id,
        DistractionEvent.timestamp >= start,
        DistractionEvent.timestamp < end,
    )

    total = db.scalar(select(func.count(DistractionEvent.id)).where(base_filter)) or 0
    manual = (
        db.scalar(select(func.count(DistractionEvent.id)).where(base_filter, DistractionEvent.event_type == DistractionType.MANUAL))
        or 0
    )
    inferred = (
        db.scalar(select(func.count(DistractionEvent.id)).where(base_filter, DistractionEvent.event_type == DistractionType.INFERRED))
        or 0
    )
    return total, manual, inferred
