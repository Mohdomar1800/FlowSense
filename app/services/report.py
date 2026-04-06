from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.models.distraction_event import DistractionEvent
from app.models.focus_session import FocusSession
from app.models.report_log import ReportLog
from app.models.user import User


def _day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=UTC)
    return start, start + timedelta(days=1)


def _build_daily_content(db: Session, user_id: int, day: date) -> str:
    start, end = _day_window(day)
    focus_seconds = db.scalar(
        select(func.coalesce(func.sum(FocusSession.duration_seconds), 0)).where(
            and_(
                FocusSession.user_id == user_id,
                FocusSession.start_time >= start,
                FocusSession.start_time < end,
            )
        )
    ) or 0
    distractions = db.scalar(
        select(func.count(DistractionEvent.id)).where(
            and_(
                DistractionEvent.user_id == user_id,
                DistractionEvent.timestamp >= start,
                DistractionEvent.timestamp < end,
            )
        )
    ) or 0

    return (
        f"Daily report for {day.isoformat()}: "
        f"total_focus_seconds={int(focus_seconds)}, total_distractions={int(distractions)}"
    )


def _build_weekly_content(db: Session, user_id: int, reference_day: date) -> str:
    week_start = reference_day - timedelta(days=reference_day.weekday())
    week_end = week_start + timedelta(days=7)

    start = datetime.combine(week_start, time.min, tzinfo=UTC)
    end = datetime.combine(week_end, time.min, tzinfo=UTC)

    focus_seconds = db.scalar(
        select(func.coalesce(func.sum(FocusSession.duration_seconds), 0)).where(
            and_(
                FocusSession.user_id == user_id,
                FocusSession.start_time >= start,
                FocusSession.start_time < end,
            )
        )
    ) or 0
    distractions = db.scalar(
        select(func.count(DistractionEvent.id)).where(
            and_(
                DistractionEvent.user_id == user_id,
                DistractionEvent.timestamp >= start,
                DistractionEvent.timestamp < end,
            )
        )
    ) or 0

    return (
        f"Weekly report ({week_start.isoformat()} to {(week_end - timedelta(days=1)).isoformat()}): "
        f"total_focus_seconds={int(focus_seconds)}, total_distractions={int(distractions)}"
    )


def generate_daily_reports(run_day: date | None = None) -> None:
    target_day = run_day or (datetime.now(UTC).date() - timedelta(days=1))
    with SessionLocal() as db:
        users = db.scalars(select(User.id)).all()
        for user_id in users:
            content = _build_daily_content(db, user_id, target_day)
            db.add(ReportLog(user_id=user_id, report_type="daily", content=content))
        db.commit()


def generate_weekly_reports(run_day: date | None = None) -> None:
    target_day = run_day or datetime.now(UTC).date()
    with SessionLocal() as db:
        users = db.scalars(select(User.id)).all()
        for user_id in users:
            content = _build_weekly_content(db, user_id, target_day)
            db.add(ReportLog(user_id=user_id, report_type="weekly", content=content))
        db.commit()


def list_reports(
    db: Session,
    user_id: int,
    report_type: str | None,
    limit: int,
    offset: int,
    start_date: date | None,
    end_date: date | None,
) -> tuple[list[ReportLog], int]:
    filters = [ReportLog.user_id == user_id]
    if report_type:
        filters.append(ReportLog.report_type == report_type)

    if start_date:
        start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)
        filters.append(ReportLog.created_at >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)
        filters.append(ReportLog.created_at < end_dt)

    base_stmt = select(ReportLog).where(and_(*filters))
    items_stmt = base_stmt.order_by(ReportLog.created_at.desc()).limit(limit).offset(offset)
    total_stmt = select(func.count(ReportLog.id)).where(and_(*filters))

    return list(db.scalars(items_stmt).all()), int(db.scalar(total_stmt) or 0)
