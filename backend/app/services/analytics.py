from datetime import date

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.timeutils import local_range_to_utc, local_today, now_utc, period_bounds
from app.models.distraction_event import DistractionEvent
from app.models.focus_session import FocusSession
from app.models.session_tag import SessionTag
from app.models.user import User
from app.schemas.analytics import (
    HourlyDistractionStat,
    ProductivityAnalyticsResponse,
    ProductivityOverview,
    TagFocusStat,
)
from app.services.focus import focus_seconds_expr

CACHE_VERSION = "v2"


def _cache_prefix(user_id: int) -> str:
    return f"analytics:{CACHE_VERSION}:user:{user_id}:"


def invalidate_productivity_cache(user_id: int) -> None:
    get_cache().delete_prefix(_cache_prefix(user_id))


def get_productivity_analytics(
    db: Session, user: User, period: str, reference_date: date | None
) -> ProductivityAnalyticsResponse:
    # Resolve "today" before building the key, so the cache rolls over at the user's midnight.
    reference = reference_date or local_today(user.timezone)
    start_date, end_date = period_bounds(period, reference)
    cache_key = f"{_cache_prefix(user.id)}productivity:{user.timezone}:{period}:{start_date.isoformat()}"

    start_dt, end_dt = local_range_to_utc(start_date, end_date, user.timezone)
    session_window = (
        FocusSession.user_id == user.id,
        FocusSession.start_time >= start_dt,
        FocusSession.start_time < end_dt,
    )

    # A running session in the period changes the numbers every second, so it is computed fresh and not cached.
    has_open_session = db.scalar(select(FocusSession.id).where(*session_window, FocusSession.end_time.is_(None)))
    cache = get_cache()
    if not has_open_session:
        cached = cache.get_json(cache_key)
        if cached is not None:
            return ProductivityAnalyticsResponse.model_validate(cached)

    distraction_window = (
        DistractionEvent.user_id == user.id,
        DistractionEvent.timestamp >= start_dt,
        DistractionEvent.timestamp < end_dt,
    )
    focus_seconds = focus_seconds_expr(now_utc())

    total_focus, session_count, avg_score = db.execute(
        select(
            func.coalesce(func.sum(focus_seconds), 0), func.count(FocusSession.id), func.avg(FocusSession.focus_score)
        ).where(*session_window)
    ).one()
    total_distractions = db.scalar(select(func.count(DistractionEvent.id)).where(*distraction_window)) or 0

    tag_focus = func.coalesce(func.sum(focus_seconds), 0)
    tag_rows = db.execute(
        select(FocusSession.tag_id, SessionTag.name, tag_focus.label("total"))
        .outerjoin(SessionTag, SessionTag.id == FocusSession.tag_id)
        .where(*session_window)
        .group_by(FocusSession.tag_id, SessionTag.name)
        .order_by(tag_focus.desc())
    ).all()

    # Group by hour in the user's local time, not UTC.
    local_hour = extract("hour", func.timezone(user.timezone, DistractionEvent.timestamp))
    hour_rows = db.execute(
        select(local_hour.label("hour"), func.count(DistractionEvent.id).label("count"))
        .where(*distraction_window)
        .group_by(local_hour)
        .order_by(local_hour)
    ).all()

    result = ProductivityAnalyticsResponse(
        overview=ProductivityOverview(
            period=period,
            start_date=start_date,
            end_date=end_date,
            total_focus_seconds=int(total_focus),
            total_distractions=int(total_distractions),
            average_session_seconds=round(total_focus / session_count, 2) if session_count else 0.0,
            focus_sessions_count=int(session_count),
            average_focus_score=round(float(avg_score), 1) if avg_score is not None else None,
        ),
        focus_by_tag=[
            TagFocusStat(tag_id=row.tag_id, tag_name=row.name, total_focus_seconds=int(row.total)) for row in tag_rows
        ],
        distractions_by_hour=[
            HourlyDistractionStat(hour=int(row.hour), distraction_count=int(row.count)) for row in hour_rows
        ],
    )

    if not has_open_session:
        cache.set_json(cache_key, result.model_dump(mode="json"), get_settings().analytics_cache_ttl_seconds)
    return result
