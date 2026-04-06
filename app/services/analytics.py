import json
import logging
from datetime import UTC, date, datetime, time, timedelta

from fastapi import HTTPException, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import and_, extract, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.distraction_event import DistractionEvent
from app.models.focus_session import FocusSession
from app.schemas.analytics import HourlyDistractionStat, ProductivityOverview, TagFocusStat

logger = logging.getLogger(__name__)
_redis_client: Redis | None = None


def _date_range(period: str, reference_date: date | None) -> tuple[date, date]:
    ref = reference_date or date.today()

    if period == "day":
        return ref, ref

    if period == "week":
        start = ref - timedelta(days=ref.weekday())
        end = start + timedelta(days=6)
        return start, end

    if period == "month":
        start = ref.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        return start, end

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="period must be day, week, or month")


def _get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis_client


def _cache_key(user_id: int, period: str, reference_date: date | None) -> str:
    reference = reference_date.isoformat() if reference_date else "auto"
    return f"analytics:productivity:user:{user_id}:period:{period}:ref:{reference}"


def _build_response(
    overview: ProductivityOverview, focus_by_tag: list[TagFocusStat], distractions_by_hour: list[HourlyDistractionStat]
) -> tuple[ProductivityOverview, list[TagFocusStat], list[HourlyDistractionStat]]:
    return overview, focus_by_tag, distractions_by_hour


def _load_cached(cache_key: str) -> tuple[ProductivityOverview, list[TagFocusStat], list[HourlyDistractionStat]] | None:
    try:
        payload = _get_redis_client().get(cache_key)
    except RedisError:
        logger.exception("analytics cache get failed")
        return None

    if not payload:
        return None

    data = json.loads(payload)
    return (
        ProductivityOverview.model_validate(data["overview"]),
        [TagFocusStat.model_validate(item) for item in data["focus_by_tag"]],
        [HourlyDistractionStat.model_validate(item) for item in data["distractions_by_hour"]],
    )


def _store_cached(
    cache_key: str,
    overview: ProductivityOverview,
    focus_by_tag: list[TagFocusStat],
    distractions_by_hour: list[HourlyDistractionStat],
) -> None:
    try:
        _get_redis_client().setex(
            cache_key,
            get_settings().analytics_cache_ttl_seconds,
            json.dumps(
                {
                    "overview": overview.model_dump(mode="json"),
                    "focus_by_tag": [item.model_dump(mode="json") for item in focus_by_tag],
                    "distractions_by_hour": [item.model_dump(mode="json") for item in distractions_by_hour],
                }
            ),
        )
    except RedisError:
        logger.exception("analytics cache set failed")


def invalidate_productivity_cache(user_id: int) -> None:
    pattern = f"analytics:productivity:user:{user_id}:*"
    try:
        client = _get_redis_client()
        keys = list(client.scan_iter(match=pattern, count=100))
        if keys:
            client.delete(*keys)
    except RedisError:
        logger.exception("analytics cache invalidation failed")


def get_productivity_analytics(
    db: Session, user_id: int, period: str, reference_date: date | None
) -> tuple[ProductivityOverview, list[TagFocusStat], list[HourlyDistractionStat]]:
    cache_key = _cache_key(user_id=user_id, period=period, reference_date=reference_date)
    cached = _load_cached(cache_key)
    if cached:
        return cached

    start_date, end_date = _date_range(period, reference_date)
    start_dt = datetime.combine(start_date, time.min, tzinfo=UTC)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=UTC)

    session_window = and_(
        FocusSession.user_id == user_id,
        FocusSession.start_time >= start_dt,
        FocusSession.start_time < end_dt,
    )

    distraction_window = and_(
        DistractionEvent.user_id == user_id,
        DistractionEvent.timestamp >= start_dt,
        DistractionEvent.timestamp < end_dt,
    )

    total_focus_seconds = db.scalar(select(func.coalesce(func.sum(FocusSession.duration_seconds), 0)).where(session_window)) or 0
    focus_sessions_count = db.scalar(select(func.count(FocusSession.id)).where(session_window)) or 0
    total_distractions = db.scalar(select(func.count(DistractionEvent.id)).where(distraction_window)) or 0

    average_session_seconds = float(total_focus_seconds / focus_sessions_count) if focus_sessions_count > 0 else 0.0

    tag_rows = db.execute(
        select(FocusSession.tag_id, func.coalesce(func.sum(FocusSession.duration_seconds), 0).label("total_focus_seconds"))
        .where(session_window)
        .group_by(FocusSession.tag_id)
        .order_by(func.coalesce(func.sum(FocusSession.duration_seconds), 0).desc())
    ).all()

    focus_by_tag = [TagFocusStat(tag_id=row.tag_id, total_focus_seconds=int(row.total_focus_seconds)) for row in tag_rows]

    hour_rows = db.execute(
        select(
            extract("hour", DistractionEvent.timestamp).label("hour"),
            func.count(DistractionEvent.id).label("distraction_count"),
        )
        .where(distraction_window)
        .group_by(extract("hour", DistractionEvent.timestamp))
        .order_by(extract("hour", DistractionEvent.timestamp).asc())
    ).all()

    distractions_by_hour = [
        HourlyDistractionStat(hour=int(row.hour), distraction_count=int(row.distraction_count)) for row in hour_rows
    ]

    overview = ProductivityOverview(
        period=period,
        start_date=start_date,
        end_date=end_date,
        total_focus_seconds=int(total_focus_seconds),
        total_distractions=int(total_distractions),
        average_session_seconds=round(average_session_seconds, 2),
        focus_sessions_count=int(focus_sessions_count),
    )

    _store_cached(cache_key, overview, focus_by_tag, distractions_by_hour)
    return _build_response(overview, focus_by_tag, distractions_by_hour)
