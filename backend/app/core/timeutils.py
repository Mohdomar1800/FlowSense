"""Timezone-aware date helpers.

All timestamps are stored in UTC. A user's "day" is a calendar day in *their* timezone,
so date filters are converted to UTC boundaries here before querying.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.errors import BadRequestError


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise BadRequestError(f"Unknown timezone: {name}") from exc
    return name


def now_utc() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC; convert aware ones to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


CLOCK_SKEW_TOLERANCE = timedelta(seconds=60)


def is_in_future(value: datetime) -> bool:
    """True if `value` is later than now, allowing for small client/server clock drift."""
    return ensure_utc(value) > now_utc() + CLOCK_SKEW_TOLERANCE


def local_today(tz: str) -> date:
    return datetime.now(ZoneInfo(tz)).date()


def local_range_to_utc(start_day: date, end_day: date, tz: str) -> tuple[datetime, datetime]:
    """Return [start, end) in UTC covering local days start_day..end_day inclusive."""
    zone = ZoneInfo(tz)
    start = datetime.combine(start_day, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(end_day + timedelta(days=1), time.min, tzinfo=zone).astimezone(UTC)
    return start, end


def period_bounds(period: str, reference: date) -> tuple[date, date]:
    """Inclusive local date bounds for day/week/month periods containing `reference`."""
    if period == "day":
        return reference, reference
    if period == "week":
        start = reference - timedelta(days=reference.weekday())
        return start, start + timedelta(days=6)
    if period == "month":
        start = reference.replace(day=1)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, next_month - timedelta(days=1)
    raise BadRequestError("period must be day, week, or month")
