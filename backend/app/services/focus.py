"""Focused-time and focus-score calculations.

Focused time = wall time since start - completed pauses - the current pause (if paused).
Ended sessions store it in duration_seconds; open sessions are computed live, both in Python
(for single sessions) and in SQL (for aggregates), using the same formula.
"""

from datetime import datetime

from sqlalchemy import Integer, case, cast, func, literal
from sqlalchemy.sql.elements import ColumnElement

from app.core.timeutils import ensure_utc
from app.models.focus_session import FocusSession, SessionStatus


def _seconds_between(start: datetime, end: datetime) -> int:
    return max(0, int((ensure_utc(end) - ensure_utc(start)).total_seconds()))


def live_focus_seconds(session: FocusSession, now: datetime) -> int:
    if session.status == SessionStatus.ENDED:
        return session.duration_seconds
    effective_end = session.paused_at if session.status == SessionStatus.PAUSED else now
    return max(0, _seconds_between(session.start_time, effective_end) - session.paused_seconds)


def focus_seconds_expr(now: datetime) -> ColumnElement[int]:
    """SQL expression for focused seconds of any session (ended or open) as of `now`."""
    now_param = literal(now)
    effective_end = func.coalesce(FocusSession.paused_at, now_param)
    open_seconds = (
        cast(func.extract("epoch", effective_end - FocusSession.start_time), Integer) - FocusSession.paused_seconds
    )
    return case(
        (FocusSession.end_time.is_(None), func.greatest(open_seconds, 0)),
        else_=FocusSession.duration_seconds,
    )


# Focus score: start at 100 and subtract penalties.
DISTRACTION_PENALTY_PER_HOURLY_RATE = 10  # points per distraction-per-hour
MAX_DISTRACTION_PENALTY = 60
PAUSE_PENALTY_WEIGHT = 40  # points at a 100% pause ratio
MAX_PAUSE_PENALTY = 20
MIN_HOURS_FOR_RATE = 0.25  # avoid huge rates for very short sessions


def compute_focus_score(focus_seconds: int, paused_seconds: int, distraction_count: int) -> int:
    """0-100. Penalizes distractions per focused hour and the share of the session spent paused."""
    focus_hours = max(focus_seconds / 3600, MIN_HOURS_FOR_RATE)
    distraction_penalty = min(
        MAX_DISTRACTION_PENALTY, distraction_count / focus_hours * DISTRACTION_PENALTY_PER_HOURLY_RATE
    )

    total = focus_seconds + paused_seconds
    pause_ratio = paused_seconds / total if total else 0
    pause_penalty = min(MAX_PAUSE_PENALTY, pause_ratio * PAUSE_PENALTY_WEIGHT)

    return max(0, min(100, round(100 - distraction_penalty - pause_penalty)))
