"""Everything the dashboard shows for one period, computed in a single pass.

A period holds at most a few hundred sessions, so rows are fetched once and bucketed in Python. That
keeps the timezone handling exact (local days and hours) and lets a session that spans several hours
spread its focus time across them in the heatmap, instead of landing entirely in its start hour.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.timeutils import ensure_utc, local_range_to_utc, now_utc
from app.models.activity import ActivityCategory, ActivitySegment
from app.models.distraction_event import DistractionEvent, DistractionType
from app.models.focus_session import FocusSession, SessionStatus
from app.models.session_tag import SessionTag
from app.models.user import User
from app.schemas.dashboard import (
    ActivityStat,
    CategoryTime,
    DashboardComparison,
    DashboardResponse,
    DashboardTotals,
    DayStat,
    DistractionStat,
    HeatCell,
    HourStat,
    TagStat,
)
from app.services.analytics import CACHE_VERSION
from app.services.focus import focus_seconds_expr, live_focus_seconds
from app.services.session import resolve_date_range
from app.services.user_settings import get_user_settings

UNTAGGED_COLOR = "#9aa1b8"
TOP_DISTRACTIONS = 6
TOP_ACTIVITIES = 8
FALLBACK_SUBJECTS = {
    DistractionType.MANUAL: "Logged manually",
    DistractionType.INFERRED: "Inactivity",
    DistractionType.SCREEN: "Off-task screen",
    DistractionType.CAMERA: "Phone",
}


@dataclass
class _SessionRow:
    start: datetime
    end: datetime  # end, or now for an open session
    focus_seconds: int
    score: int | None
    tag_id: int | None


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _spread_over_hours(row: _SessionRow, zone: ZoneInfo, hours: dict, heat: dict) -> None:
    """Split a session's focus time across the local clock hours it covered (pauses spread evenly)."""
    wall = (row.end - row.start).total_seconds()
    if wall <= 0 or row.focus_seconds <= 0:
        return
    focus_per_wall_second = row.focus_seconds / wall
    cursor = row.start.astimezone(zone)
    end = row.end.astimezone(zone)
    while cursor < end:
        next_hour = (cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).astimezone(zone)
        chunk_end = min(next_hour, end)
        seconds = (chunk_end - cursor).total_seconds() * focus_per_wall_second
        hours[cursor.hour] += seconds
        heat[(cursor.weekday(), cursor.hour)] += seconds
        cursor = chunk_end


def _comparison(db: Session, user: User, first: date, last: date, now: datetime) -> DashboardComparison:
    length = (last - first).days + 1
    prev_last = first - timedelta(days=1)
    prev_first = prev_last - timedelta(days=length - 1)
    start, end = local_range_to_utc(prev_first, prev_last, user.timezone)
    focus, avg_score = db.execute(
        select(func.coalesce(func.sum(focus_seconds_expr(now)), 0), func.avg(FocusSession.focus_score)).where(
            FocusSession.user_id == user.id, FocusSession.start_time >= start, FocusSession.start_time < end
        )
    ).one()
    distractions = db.scalar(
        select(func.count(DistractionEvent.id)).where(
            DistractionEvent.user_id == user.id, DistractionEvent.timestamp >= start, DistractionEvent.timestamp < end
        )
    )
    return DashboardComparison(
        start_date=prev_first,
        end_date=prev_last,
        focus_seconds=int(focus),
        distractions=int(distractions or 0),
        average_focus_score=round(float(avg_score), 1) if avg_score is not None else None,
    )


def get_dashboard(
    db: Session,
    user: User,
    period: str,
    reference_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> DashboardResponse:
    first, last = resolve_date_range(user, period, reference_date, start_date, end_date)
    start_dt, end_dt = local_range_to_utc(first, last, user.timezone)
    zone = ZoneInfo(user.timezone)
    now = now_utc()

    in_range = (FocusSession.user_id == user.id, FocusSession.start_time >= start_dt, FocusSession.start_time < end_dt)
    has_open = db.scalar(select(FocusSession.id).where(*in_range, FocusSession.end_time.is_(None)))
    cache = get_cache()
    # The period is part of the key: a "day" and a one-day "custom" range (used by reports) cover the same dates
    # but differ in shape (the day view's trend is hourly).
    key = f"analytics:{CACHE_VERSION}:user:{user.id}:dashboard:{period}:{user.timezone}:{first}:{last}"
    if not has_open and (cached := cache.get_json(key)) is not None:
        return DashboardResponse.model_validate(cached)

    goal_seconds = get_user_settings(db, user).daily_focus_goal_minutes * 60

    # ---------- sessions ----------
    rows: list[_SessionRow] = []
    for s in db.scalars(select(FocusSession).where(*in_range)):
        end = ensure_utc(s.end_time) if s.end_time else (ensure_utc(s.paused_at) if s.paused_at else now)
        score = s.focus_score if s.status == SessionStatus.ENDED else None
        rows.append(_SessionRow(ensure_utc(s.start_time), end, live_focus_seconds(s, now), score, s.tag_id))

    day_focus: dict[date, float] = defaultdict(float)
    day_sessions: dict[date, int] = defaultdict(int)
    day_scores: dict[date, list[int]] = defaultdict(list)
    hour_focus: dict[int, float] = defaultdict(float)
    heat: dict[tuple[int, int], float] = defaultdict(float)
    tag_focus: dict[int | None, int] = defaultdict(int)
    for row in rows:
        local_day = row.start.astimezone(zone).date()  # a session belongs to the day it started
        day_focus[local_day] += row.focus_seconds
        day_sessions[local_day] += 1
        if row.score is not None:
            day_scores[local_day].append(row.score)
        tag_focus[row.tag_id] += row.focus_seconds
        _spread_over_hours(row, zone, hour_focus, heat)

    # ---------- distractions ----------
    distractions = list(
        db.execute(
            select(
                DistractionEvent.timestamp,
                DistractionEvent.event_type,
                DistractionEvent.subject,
                DistractionEvent.duration_seconds,
            ).where(
                DistractionEvent.user_id == user.id,
                DistractionEvent.timestamp >= start_dt,
                DistractionEvent.timestamp < end_dt,
            )
        )
    )
    day_distractions: dict[date, int] = defaultdict(int)
    hour_distractions: dict[int, int] = defaultdict(int)
    by_subject: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for timestamp, kind, subject, duration in distractions:
        local = ensure_utc(timestamp).astimezone(zone)
        day_distractions[local.date()] += 1
        hour_distractions[local.hour] += 1
        stat = by_subject[(subject or FALLBACK_SUBJECTS[kind], kind.value)]
        stat[0] += 1
        stat[1] += duration or 0

    # ---------- screen activity ----------
    segment_seconds = func.extract("epoch", func.coalesce(ActivitySegment.ended_at, now) - ActivitySegment.started_at)
    activity_rows = db.execute(
        select(ActivitySegment.subject, ActivitySegment.category, func.sum(segment_seconds))
        .where(
            ActivitySegment.user_id == user.id,
            ActivitySegment.started_at >= start_dt,
            ActivitySegment.started_at < end_dt,
        )
        .group_by(ActivitySegment.subject, ActivitySegment.category)
    ).all()
    category_time = {category: 0 for category in ActivityCategory}
    for _, category, seconds in activity_rows:
        category_time[category] += int(seconds or 0)

    # ---------- assemble ----------
    tag_meta = {t.id: t for t in db.scalars(select(SessionTag).where(SessionTag.user_id == user.id))}
    finished_scores = [r.score for r in rows if r.score is not None]
    total_focus = sum(r.focus_seconds for r in rows)
    span = (last - first).days + 1

    result = DashboardResponse(
        period=period,
        start_date=first,
        end_date=last,
        daily_goal_seconds=goal_seconds,
        totals=DashboardTotals(
            focus_seconds=total_focus,
            sessions=len(rows),
            average_session_seconds=round(total_focus / len(rows), 1) if rows else 0.0,
            average_focus_score=_mean(finished_scores),
            distractions=len(distractions),
            time_lost_seconds=sum(d[3] or 0 for d in distractions),
        ),
        previous=_comparison(db, user, first, last, now),
        days=[
            DayStat(
                date=day,
                focus_seconds=int(day_focus[day]),
                sessions=day_sessions[day],
                distractions=day_distractions[day],
                average_focus_score=_mean(day_scores[day]),
                goal_met=goal_seconds > 0 and day_focus[day] >= goal_seconds,
            )
            for day in (first + timedelta(days=i) for i in range(span))
        ],
        hours=[
            HourStat(hour=h, focus_seconds=int(round(hour_focus[h])), distractions=hour_distractions[h])
            for h in range(24)
        ],
        heatmap=[
            HeatCell(weekday=wd, hour=h, focus_seconds=int(round(seconds)))
            for (wd, h), seconds in sorted(heat.items())
            if seconds >= 1
        ],
        tags=sorted(
            (
                TagStat(
                    tag_id=tag_id,
                    name=tag_meta[tag_id].name if tag_id in tag_meta else "No tag",
                    color=tag_meta[tag_id].color if tag_id in tag_meta else UNTAGGED_COLOR,
                    focus_seconds=seconds,
                )
                for tag_id, seconds in tag_focus.items()
                if seconds > 0
            ),
            key=lambda t: -t.focus_seconds,
        ),
        top_distractions=[
            DistractionStat(subject=subject, source=source, count=count, time_lost_seconds=lost)
            for (subject, source), (count, lost) in sorted(by_subject.items(), key=lambda kv: (-kv[1][0], -kv[1][1]))[
                :TOP_DISTRACTIONS
            ]
        ],
        screen_time=CategoryTime(**{c.value: s for c, s in category_time.items()}),
        top_activities=[
            ActivityStat(subject=subject, category=category.value, seconds=int(seconds or 0))
            for subject, category, seconds in sorted(activity_rows, key=lambda r: -(r[2] or 0))[:TOP_ACTIVITIES]
        ],
    )
    if not has_open:
        cache.set_json(key, result.model_dump(mode="json"), get_settings().analytics_cache_ttl_seconds)
    return result
