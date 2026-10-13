"""Personal insights from the last four weeks of sessions and distractions.

Each rule is a small function that looks at a shared snapshot of the user's history and returns an
insight or None. A rule only speaks when it has enough data, and every insight carries the evidence
it was based on, so nothing is a guess dressed up as advice.

Adding a rule: write `def _my_rule(h: History) -> Candidate | None` and add it to RULES.
"""

import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cache import get_cache
from app.core.config import get_settings
from app.core.timeutils import ensure_utc, now_utc
from app.models.distraction_event import DistractionEvent, DistractionType
from app.models.focus_session import FocusSession, SessionStatus
from app.models.session_event import SessionEvent, SessionEventType
from app.models.user import User
from app.schemas.insight import InsightItem, InsightResponse
from app.services.analytics import CACHE_VERSION
from app.services.user_settings import get_user_settings

LOOKBACK_DAYS = 28
MAX_INSIGHTS = 8
MIN_SESSIONS = 3

# ---------------------------------------------------------------------------
# History snapshot
# ---------------------------------------------------------------------------


@dataclass
class SessionInfo:
    start: datetime  # local time
    focus_seconds: int
    paused_seconds: int
    score: int | None
    tagged: bool
    # Seconds into the session (wall clock) at which each distraction happened.
    distraction_offsets: list[float] = field(default_factory=list)


@dataclass
class DistractionInfo:
    when: datetime  # local time
    kind: DistractionType
    subject: str | None
    duration: int


@dataclass
class History:
    today: date
    goal_seconds: int
    sessions: list[SessionInfo]
    distractions: list[DistractionInfo]
    long_pause_splits: int
    first_day: date | None  # first local day with a session in the window

    def focus_by_day(self) -> dict[date, int]:
        days: dict[date, int] = defaultdict(int)
        for s in self.sessions:
            days[s.start.date()] += s.focus_seconds
        return days


def _load_history(db: Session, user: User, now: datetime) -> History:
    zone = ZoneInfo(user.timezone)
    since = now - timedelta(days=LOOKBACK_DAYS)
    sessions = list(
        db.scalars(
            select(FocusSession).where(
                FocusSession.user_id == user.id,
                FocusSession.status == SessionStatus.ENDED,
                FocusSession.start_time >= since,
            )
        )
    )
    by_id: dict[int, SessionInfo] = {}
    infos: list[SessionInfo] = []
    for s in sessions:
        info = SessionInfo(
            start=ensure_utc(s.start_time).astimezone(zone),
            focus_seconds=s.duration_seconds,
            paused_seconds=s.paused_seconds,
            score=s.focus_score,
            tagged=s.tag_id is not None,
        )
        by_id[s.id] = info
        infos.append(info)

    distractions: list[DistractionInfo] = []
    for d in db.scalars(
        select(DistractionEvent).where(DistractionEvent.user_id == user.id, DistractionEvent.timestamp >= since)
    ):
        when = ensure_utc(d.timestamp).astimezone(zone)
        distractions.append(DistractionInfo(when, d.event_type, d.subject, d.duration_seconds or 0))
        if d.session_id in by_id:
            session = by_id[d.session_id]
            by_id[d.session_id].distraction_offsets.append((when - session.start).total_seconds())

    splits = 0
    if by_id:
        for details in db.scalars(
            select(SessionEvent.details).where(
                SessionEvent.session_id.in_(by_id), SessionEvent.event_type == SessionEventType.STOPPED
            )
        ):
            if details and details.get("reason") == "long_pause":
                splits += 1

    return History(
        today=now.astimezone(zone).date(),
        goal_seconds=get_user_settings(db, user).daily_focus_goal_minutes * 60,
        sessions=infos,
        distractions=distractions,
        long_pause_splits=splits,
        first_day=min((s.start.date() for s in infos), default=None),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    item: InsightItem
    impact: float  # higher shows first


def _insight(id_, kind, title, message, tip, evidence, confidence, impact) -> Candidate:
    item = InsightItem(
        id=id_, kind=kind, title=title, message=message, tip=tip, evidence=evidence, confidence=confidence
    )
    return Candidate(item, impact)


def _confidence(samples: int, medium: int, high: int) -> str:
    return "high" if samples >= high else "medium" if samples >= medium else "low"


def _duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes} min"


def _clock(hour: int) -> str:
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


BLOCKS = [(0, 6), (6, 9), (9, 12), (12, 15), (15, 18), (18, 21), (21, 24)]


def _block_of(hour: int) -> tuple[int, int]:
    return next(b for b in BLOCKS if b[0] <= hour < b[1])


def _block_label(block: tuple[int, int]) -> str:
    return "late at night" if block == (0, 6) else f"{_clock(block[0])}–{_clock(block[1])}"


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _time_of_day(h: History) -> list[Candidate]:
    """Best and worst 3-hour windows by average focus score (needs 3+ sessions in a window)."""
    scored = [s for s in h.sessions if s.score is not None]
    if len(scored) < 6:
        return []
    overall = statistics.mean(s.score for s in scored)
    blocks: dict[tuple[int, int], list[int]] = defaultdict(list)
    for s in scored:
        blocks[_block_of(s.start.hour)].append(s.score)
    eligible = {b: v for b, v in blocks.items() if len(v) >= 3}
    if len(eligible) < 2:
        return []

    out = []
    best = max(eligible, key=lambda b: statistics.mean(eligible[b]))
    best_avg = statistics.mean(eligible[best])
    if best_avg - overall >= 5:
        out.append(
            _insight(
                "best_window",
                "strength",
                f"You focus best {_block_label(best)}",
                f"Sessions you start {_block_label(best)} score {best_avg:.0f} on average, "
                f"compared with {overall:.0f} overall.",
                "Protect this window for your hardest work: lectures, problem sets, deep reading.",
                f"{len(eligible[best])} sessions in that window, {len(scored)} sessions in total",
                _confidence(len(eligible[best]), 4, 8),
                40 + (best_avg - overall),
            )
        )
    worst = min(eligible, key=lambda b: statistics.mean(eligible[b]))
    worst_avg = statistics.mean(eligible[worst])
    if worst != best and overall - worst_avg >= 8:
        out.append(
            _insight(
                "worst_window",
                "improve",
                f"Focus dips {_block_label(worst)}",
                f"Sessions you start {_block_label(worst)} score {worst_avg:.0f} on average, "
                f"{overall - worst_avg:.0f} points below your usual {overall:.0f}.",
                "Use that time for lighter work (review, admin, flashcards), or try shorter sessions then.",
                f"{len(eligible[worst])} sessions in that window",
                _confidence(len(eligible[worst]), 4, 8),
                55 + (overall - worst_avg),
            )
        )
    return out


def _session_length(h: History) -> Candidate | None:
    """Find when distractions start climbing inside a session, from distraction rate per 15-minute slice."""
    sessions = [s for s in h.sessions if s.focus_seconds >= 30 * 60]
    total_distractions = sum(len(s.distraction_offsets) for s in sessions)
    if len(sessions) < 8 or total_distractions < 6:
        return None

    bucket = 15 * 60
    exposure: dict[int, float] = defaultdict(float)  # hours of session time spent in each slice
    counts: dict[int, int] = defaultdict(int)
    for s in sessions:
        wall = s.focus_seconds + s.paused_seconds
        for b in range(int(wall // bucket) + 1):
            exposure[b] += max(0.0, min(bucket, wall - b * bucket)) / 3600
        for offset in s.distraction_offsets:
            if 0 <= offset <= wall:
                counts[int(offset // bucket)] += 1

    # Change point: the cut-off (30, 45, 60... min) where the rate after it most exceeds the rate before it.
    # Comparing whole before/after spans (not single slices) keeps one busy slice from looking like a trend.
    last = max(exposure)
    best = None
    for cut in range(2, last + 1):
        before_hours = sum(exposure[b] for b in range(cut))
        after_hours = sum(exposure[b] for b in range(cut, last + 1))
        if after_hours < 1.5:  # under 90 minutes of data past this point: not enough to judge
            break
        before = sum(counts[b] for b in range(cut)) / before_hours
        after = sum(counts[b] for b in range(cut, last + 1)) / after_hours
        if after >= max(1.0, before * 1.5) and (best is None or after - before > best[1] - best[2]):
            best = (cut, after, before)
    if best is None:
        return None

    cut, after, before = best
    minutes = cut * 15
    suggestion = max(20, minutes - 5)
    return _insight(
        "session_length",
        "improve",
        f"Distractions climb after about {minutes} minutes",
        f"In your longer sessions you're distracted {after:.1f} times an hour after the {minutes}-minute mark, "
        f"compared with {before:.1f} an hour before it.",
        f"Try {suggestion}-minute sessions with a 5-minute break in between.",
        f"{len(sessions)} sessions of 30+ minutes, {total_distractions} distractions",
        _confidence(len(sessions), 10, 20),
        70 + 10 * (after - before),
    )


def _costliest_distraction(h: History) -> Candidate | None:
    detected = [d for d in h.distractions if d.kind in (DistractionType.SCREEN, DistractionType.CAMERA)]
    totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for d in detected:
        totals[d.subject or "Off-task screen"][0] += d.duration
        totals[d.subject or "Off-task screen"][1] += 1
    if not totals:
        return None
    subject, (seconds, count) = max(totals.items(), key=lambda kv: (kv[1][0], kv[1][1]))
    if seconds < 10 * 60 and count < 5:
        return None
    if subject == "Phone":
        tip = "Put your phone in another room, or face down out of reach, before you press Start."
    else:
        tip = (
            f'Close {subject} before a session. If it keeps happening, add an "Always flag" rule in Settings '
            "or use a site blocker during focus time."
        )
    return _insight(
        "costliest_distraction",
        "improve",
        f"{subject} is your biggest time sink",
        f"{subject} pulled you away {count} time{'s' if count != 1 else ''} in the last four weeks, "
        f"costing about {_duration(seconds)}.",
        tip,
        f"{count} episodes, {_duration(seconds)} in total",
        _confidence(count, 4, 10),
        60 + seconds / 600,
    )


def _phone_trend(h: History) -> Candidate | None:
    week_start = h.today - timedelta(days=6)
    phone = [d for d in h.distractions if d.kind == DistractionType.CAMERA]
    this_week = sum(1 for d in phone if d.when.date() >= week_start)
    last_week = sum(1 for d in phone if week_start - timedelta(days=7) <= d.when.date() < week_start)
    if last_week >= 3 and this_week <= last_week * 0.6:
        return _insight(
            "phone_down",
            "strength",
            "Fewer phone pickups",
            f"You picked up your phone {this_week} time{'s' if this_week != 1 else ''} during sessions this week, "
            f"down from {last_week} the week before.",
            "",
            f"{this_week} vs {last_week} camera-detected pickups",
            "medium",
            35,
        )
    if this_week >= 5 and this_week >= last_week * 1.5:
        return _insight(
            "phone_up",
            "improve",
            "Phone pickups are rising",
            f"The camera saw you reach for your phone {this_week} times this week, up from {last_week}.",
            "Turn on Do Not Disturb, or leave the phone in another room for the next session.",
            f"{this_week} vs {last_week} camera-detected pickups",
            "medium",
            58,
        )
    return None


def _weekly_trend(h: History) -> Candidate | None:
    days = h.focus_by_day()
    week_start = h.today - timedelta(days=6)
    this_week = sum(v for d, v in days.items() if d >= week_start)
    last_week = sum(v for d, v in days.items() if week_start - timedelta(days=7) <= d < week_start)
    if last_week < 60 * 60:
        return None
    change = (this_week - last_week) / last_week
    evidence = f"{_duration(this_week)} in the last 7 days vs {_duration(last_week)} the week before"
    if change >= 0.15:
        return _insight(
            "trend_up",
            "strength",
            f"Focus time is up {change:.0%}",
            f"You focused {_duration(this_week)} in the last 7 days, up from {_duration(last_week)}.",
            "",
            evidence,
            "high",
            45 + 20 * change,
        )
    if change <= -0.2:
        return _insight(
            "trend_down",
            "improve",
            f"Focus time is down {-change:.0%}",
            f"You focused {_duration(this_week)} in the last 7 days, down from {_duration(last_week)}.",
            "Pick one fixed time each day for a single session; consistency matters more than length.",
            evidence,
            "high",
            50 + 20 * -change,
        )
    return None


def _goal(h: History) -> Candidate | None:
    if h.goal_seconds <= 0 or h.first_day is None:
        return None
    days = h.focus_by_day()

    streak, day = 0, h.today
    if days.get(day, 0) < h.goal_seconds:
        day -= timedelta(days=1)  # today isn't over yet: count the streak up to yesterday
    while days.get(day, 0) >= h.goal_seconds:
        streak += 1
        day -= timedelta(days=1)
    if streak >= 3:
        return _insight(
            "goal_streak",
            "strength",
            f"{streak}-day goal streak",
            f"You've hit your daily goal of {_duration(h.goal_seconds)} {streak} days in a row.",
            "",
            f"Goal met every day since {(day + timedelta(days=1)).strftime('%b %d')}",
            "high",
            50 + streak,
        )

    recent = [h.today - timedelta(days=i) for i in range(1, 8) if h.today - timedelta(days=i) >= h.first_day]
    active = [days[d] for d in recent if days.get(d, 0) > 0]
    met = sum(1 for d in recent if days.get(d, 0) >= h.goal_seconds)
    if len(active) >= 4 and met <= 1:
        typical = statistics.median(active)
        suggested = max(15, int(round(typical * 1.1 / 900)) * 15)  # ~10% above a typical day, in 15-minute steps
        if suggested * 60 < h.goal_seconds:
            return _insight(
                "goal_too_high",
                "improve",
                "Your daily goal may be too ambitious",
                f"You met your {_duration(h.goal_seconds)} goal on {met} of the last {len(recent)} days. "
                f"A typical focused day for you is about {_duration(typical)}.",
                f"Set your goal to {suggested} minutes in Settings. Hitting a smaller goal every day builds the habit, "
                "and you can raise it later.",
                f"{len(active)} active days, median {_duration(typical)}",
                "medium",
                52,
            )
    return None


def _weakest_weekday(h: History) -> Candidate | None:
    if h.first_day is None or (h.today - h.first_day).days < 21:
        return None
    days = h.focus_by_day()
    totals: dict[int, list[int]] = defaultdict(list)
    day = h.first_day
    while day < h.today:
        totals[day.weekday()].append(days.get(day, 0))
        day += timedelta(days=1)
    averages = {wd: statistics.mean(v) for wd, v in totals.items() if len(v) >= 3}
    if len(averages) < 7:
        return None
    overall = statistics.mean(averages.values())
    weakest = min(averages, key=averages.get)
    if overall < 30 * 60 or averages[weakest] > overall * 0.5:
        return None
    name = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"][weakest]
    return _insight(
        "weak_weekday",
        "info",
        f"{name}s are your quietest day",
        f"You average {_duration(averages[weakest])} of focus on {name}s, "
        f"against {_duration(overall)} on a typical day.",
        f"If that's intentional rest, great. If not, plan one short session for {name} mornings.",
        f"Based on {len(totals[weakest])} {name}s",
        "medium",
        25,
    )


def _short_sessions(h: History) -> Candidate | None:
    if len(h.sessions) < 6:
        return None
    short = [s for s in h.sessions if s.focus_seconds < 10 * 60]
    share = len(short) / len(h.sessions)
    if share < 0.3:
        return None
    return _insight(
        "short_sessions",
        "improve",
        "Sessions often end early",
        f"{len(short)} of your last {len(h.sessions)} sessions ({share:.0%}) lasted under 10 minutes.",
        'Before pressing Start, write one specific goal in "What are you working on?" and aim for 25 minutes.',
        f"{len(short)} sessions under 10 minutes",
        _confidence(len(h.sessions), 8, 15),
        48 + 30 * share,
    )


def _long_breaks(h: History) -> Candidate | None:
    if h.long_pause_splits < 3:
        return None
    return _insight(
        "long_breaks",
        "improve",
        "Breaks tend to run long",
        f"{h.long_pause_splits} of your breaks in the last four weeks ran past your long-break limit "
        "and ended the session.",
        "Set a timer when you pause. A 5-minute break that stays 5 minutes keeps your momentum.",
        f"{h.long_pause_splits} sessions split by a long pause",
        _confidence(h.long_pause_splits, 4, 8),
        40 + h.long_pause_splits,
    )


def _stepping_away(h: History) -> Candidate | None:
    idle = [d for d in h.distractions if d.kind == DistractionType.INFERRED]
    if len(idle) < 4:
        return None
    return _insight(
        "stepping_away",
        "improve",
        "You often step away mid-session",
        f"FlowSense noticed {len(idle)} stretches with no keyboard or mouse activity during sessions.",
        "Press Pause when you get up. Your focus time and score will reflect your real work.",
        f"{len(idle)} inactivity events",
        _confidence(len(idle), 6, 12),
        38,
    )


def _untagged(h: History) -> Candidate | None:
    if len(h.sessions) < 5:
        return None
    untagged = sum(1 for s in h.sessions if not s.tagged)
    if untagged / len(h.sessions) < 0.6:
        return None
    return _insight(
        "tag_sessions",
        "info",
        "Tag your sessions for sharper insights",
        f"{untagged} of your {len(h.sessions)} recent sessions have no tag.",
        "Create tags for your subjects or projects in Settings, then pick one before you start.",
        f"{untagged} untagged sessions",
        "high",
        15,
    )


RULES = (
    _time_of_day,
    _session_length,
    _costliest_distraction,
    _phone_trend,
    _weekly_trend,
    _goal,
    _weakest_weekday,
    _short_sessions,
    _long_breaks,
    _stepping_away,
    _untagged,
)


def _getting_started(sessions: int) -> list[InsightItem]:
    remaining = MIN_SESSIONS - sessions
    return [
        InsightItem(
            id="getting_started",
            kind="info",
            title="Insights are on their way",
            message=f"Finish {remaining} more session{'s' if remaining != 1 else ''} and FlowSense will start spotting "
            "your patterns: when you focus best, what distracts you, and how long your sessions should be.",
            tip="Start with a 25-minute session on one specific task.",
            evidence=f"{sessions} finished session{'s' if sessions != 1 else ''} so far",
            confidence="high",
        )
    ]


def build_insights(db: Session, user: User) -> InsightResponse:
    cache = get_cache()
    key = f"analytics:{CACHE_VERSION}:user:{user.id}:insights:{user.timezone}"
    if (cached := cache.get_json(key)) is not None:
        return InsightResponse.model_validate(cached)

    history = _load_history(db, user, now_utc())
    if len(history.sessions) < MIN_SESSIONS:
        items = _getting_started(len(history.sessions))
    else:
        candidates: list[Candidate] = []
        for rule in RULES:
            result = rule(history)
            if isinstance(result, list):
                candidates.extend(result)
            elif result is not None:
                candidates.append(result)
        candidates.sort(key=lambda c: -c.impact)
        items = [c.item for c in candidates[:MAX_INSIGHTS]]
        if not items:
            items = [
                InsightItem(
                    id="steady",
                    kind="strength",
                    title="Steady and consistent",
                    message="Nothing stands out in your recent sessions: no worrying patterns, no big swings.",
                    tip="Keep going. As your history grows, FlowSense can spot finer patterns.",
                    evidence=f"{len(history.sessions)} sessions in the last {LOOKBACK_DAYS} days",
                    confidence="medium",
                )
            ]

    response = InsightResponse(lookback_days=LOOKBACK_DAYS, sessions_analyzed=len(history.sessions), items=items)
    cache.set_json(key, response.model_dump(mode="json"), get_settings().analytics_cache_ttl_seconds)
    return response
