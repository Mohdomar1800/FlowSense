from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models.focus_session import FocusSession
from app.services.analytics import invalidate_productivity_cache


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def get_active_session(db: Session, user_id: int) -> FocusSession | None:
    return db.scalar(select(FocusSession).where(FocusSession.user_id == user_id, FocusSession.end_time.is_(None)))


def start_session(db: Session, user_id: int, tag_id: int | None, start_time: datetime | None) -> FocusSession:
    active_session = get_active_session(db, user_id)
    if active_session:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="You already have an active session")

    session = FocusSession(user_id=user_id, tag_id=tag_id, start_time=_ensure_utc(start_time) if start_time else _now_utc())
    db.add(session)
    db.commit()
    db.refresh(session)
    invalidate_productivity_cache(user_id)
    return session


def stop_session(db: Session, user_id: int, end_time: datetime | None) -> FocusSession:
    session = get_active_session(db, user_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active session found")

    session_start_time = _ensure_utc(session.start_time)
    resolved_end_time = _ensure_utc(end_time) if end_time else _now_utc()
    if resolved_end_time < session_start_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_time cannot be before start_time")

    session.end_time = resolved_end_time
    session.duration_seconds = int((resolved_end_time - session_start_time).total_seconds())
    db.commit()
    db.refresh(session)
    invalidate_productivity_cache(user_id)
    return session


def pause_session(db: Session, user_id: int, paused_at: datetime, resumed_at: datetime) -> tuple[FocusSession, FocusSession | None]:
    paused_at = _ensure_utc(paused_at)
    resumed_at = _ensure_utc(resumed_at)
    if resumed_at <= paused_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="resumed_at must be after paused_at")

    session = get_active_session(db, user_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active session found")

    session_start_time = _ensure_utc(session.start_time)
    pause_seconds = int((resumed_at - paused_at).total_seconds())
    if pause_seconds <= session.pause_threshold_seconds:
        return session, None

    if paused_at < session_start_time:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="paused_at cannot be before session start")

    session.end_time = paused_at
    session.duration_seconds = int((paused_at - session_start_time).total_seconds())

    new_session = FocusSession(
        user_id=user_id,
        tag_id=session.tag_id,
        start_time=resumed_at,
        pause_threshold_seconds=session.pause_threshold_seconds,
    )
    db.add(new_session)
    db.commit()
    db.refresh(session)
    db.refresh(new_session)
    invalidate_productivity_cache(user_id)
    return session, new_session


def _resolve_range(period: str, reference_date: date | None, start_date: date | None, end_date: date | None) -> tuple[datetime, datetime]:
    ref = reference_date or date.today()
    if period == "day":
        start = datetime.combine(ref, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        return start, end

    if period == "week":
        week_start = ref - timedelta(days=ref.weekday())
        start = datetime.combine(week_start, time.min, tzinfo=UTC)
        end = start + timedelta(days=7)
        return start, end

    if period == "month":
        month_start = ref.replace(day=1)
        if month_start.month == 12:
            next_month = month_start.replace(year=month_start.year + 1, month=1)
        else:
            next_month = month_start.replace(month=month_start.month + 1)
        start = datetime.combine(month_start, time.min, tzinfo=UTC)
        end = datetime.combine(next_month, time.min, tzinfo=UTC)
        return start, end

    if period == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="custom range requires start_date and end_date")
        if end_date < start_date:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end_date must be >= start_date")
        start = datetime.combine(start_date, time.min, tzinfo=UTC)
        end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        return start, end

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported period")


def list_sessions(
    db: Session, user_id: int, period: str, reference_date: date | None, start_date: date | None, end_date: date | None
) -> tuple[list[FocusSession], int]:
    range_start, range_end = _resolve_range(period, reference_date, start_date, end_date)

    stmt = (
        select(FocusSession)
        .where(
            and_(
                FocusSession.user_id == user_id,
                FocusSession.start_time >= range_start,
                FocusSession.start_time < range_end,
            )
        )
        .order_by(FocusSession.start_time.desc())
    )
    sessions = list(db.scalars(stmt).all())
    total_focus_seconds = sum(session.duration_seconds for session in sessions)
    return sessions, total_focus_seconds
