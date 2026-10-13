"""Daily and weekly reports: a frozen recap of each finished day/week, with highlights and one next goal.

Numbers come from the dashboard computation, so a report always agrees with what the dashboard showed
for the same period. Reports are generated after the user's local midnight (and on startup, to catch
up), skipped for periods with no activity, and inserted idempotently: one per user, type and period.
"""

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.core.events import publish_user_event
from app.core.timeutils import ensure_utc, local_range_to_utc, now_utc
from app.db.session import SessionLocal
from app.models.distraction_event import DistractionEvent
from app.models.focus_session import FocusSession, SessionStatus
from app.models.report_log import ReportLog
from app.models.session_tag import SessionTag
from app.models.user import User
from app.schemas.dashboard import DashboardResponse
from app.schemas.report import (
    BestSession,
    ReportComparison,
    ReportData,
    ReportDay,
    ReportDistraction,
    ReportLogResponse,
    ReportTag,
    ReportTotals,
)
from app.services.dashboard import get_dashboard

logger = logging.getLogger(__name__)


def _duration(seconds: float) -> str:
    minutes = int(round(seconds / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def _title(report_type: str, first: date, last: date) -> str:
    if report_type == "daily":
        return f"{first.strftime('%A, %b')} {first.day}"
    return f"Week of {first.strftime('%b')} {first.day} – {last.strftime('%b')} {last.day}"


def _has_activity(db: Session, user: User, first: date, last: date) -> bool:
    start, end = local_range_to_utc(first, last, user.timezone)
    session = db.scalar(
        select(FocusSession.id).where(
            FocusSession.user_id == user.id, FocusSession.start_time >= start, FocusSession.start_time < end
        )
    )
    if session is not None:
        return True
    distraction = db.scalar(
        select(DistractionEvent.id).where(
            DistractionEvent.user_id == user.id, DistractionEvent.timestamp >= start, DistractionEvent.timestamp < end
        )
    )
    return distraction is not None


def _best_session(db: Session, user: User, first: date, last: date) -> BestSession | None:
    start, end = local_range_to_utc(first, last, user.timezone)
    row = db.execute(
        select(FocusSession, SessionTag.name)
        .outerjoin(SessionTag, SessionTag.id == FocusSession.tag_id)
        .where(
            FocusSession.user_id == user.id,
            FocusSession.status == SessionStatus.ENDED,
            FocusSession.start_time >= start,
            FocusSession.start_time < end,
            FocusSession.duration_seconds >= 5 * 60,
        )
        # Best = highest score, then longest; scores are only comparable for sessions of real length.
        .order_by(FocusSession.focus_score.desc().nulls_last(), FocusSession.duration_seconds.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    session, tag_name = row
    return BestSession(
        start_time=ensure_utc(session.start_time),
        focus_seconds=session.duration_seconds,
        focus_score=session.focus_score,
        label=session.intent or tag_name or "Focus session",
    )


def _highlights(report_type: str, d: DashboardResponse, best: BestSession | None, on_task: float | None) -> list[str]:
    t, p = d.totals, d.previous
    unit = "day" if report_type == "daily" else "week"
    out: list[str] = []
    goal = d.daily_goal_seconds
    met = sum(day.goal_met for day in d.days)
    if goal and report_type == "daily" and met:
        out.append(f"You hit your {_duration(goal)} daily goal.")
    elif goal and report_type == "weekly" and met:
        out.append(f"Daily goal met on {met} of {len(d.days)} days.")
    if p.focus_seconds and t.focus_seconds >= p.focus_seconds * 1.1:
        out.append(f"{(t.focus_seconds - p.focus_seconds) / p.focus_seconds:.0%} more focus than the {unit} before.")
    if best:
        score = f" with a focus score of {best.focus_score}" if best.focus_score is not None else ""
        out.append(f"Best session: {_duration(best.focus_seconds)} on “{best.label}”{score}.")
    if t.sessions and t.distractions == 0:
        out.append("No distractions at all. Excellent focus.")
    elif p.distractions and t.distractions < p.distractions:
        out.append(f"Fewer distractions than the {unit} before ({t.distractions} vs {p.distractions}).")
    if t.average_focus_score is not None and t.average_focus_score >= 85:
        out.append(f"Average focus score of {t.average_focus_score:.0f}.")
    if on_task is not None and on_task >= 0.8:
        out.append(f"{on_task:.0%} of your screen time was on task.")
    return out


def _next_goal(report_type: str, d: DashboardResponse, top: ReportDistraction | None) -> str:
    t = d.totals
    when = "tomorrow" if report_type == "daily" else "next week"
    if top and top.time_lost_seconds >= 5 * 60:
        if top.subject == "Phone":
            return (
                f"Keep your phone out of reach during sessions {when}. It cost you {_duration(top.time_lost_seconds)}."
            )
        return f"Keep {top.subject} closed during sessions {when}. It cost you {_duration(top.time_lost_seconds)}."
    goal = d.daily_goal_seconds
    met = sum(day.goal_met for day in d.days)
    if goal and report_type == "daily" and not met:
        return f"Reach your {_duration(goal)} goal tomorrow: {_duration(goal - t.focus_seconds)} more than today."
    if goal and report_type == "weekly" and met < len(d.days):
        return f"Meet your daily goal on at least {min(len(d.days), met + 1)} days next week."
    if t.average_focus_score is not None and t.average_focus_score < 70:
        return (
            f"Aim for a focus score above {int(t.average_focus_score) + 10} {when}: try shorter sessions with a break."
        )
    unit = "day" if report_type == "daily" else "week"
    return f"Beat this {unit}'s {_duration(t.focus_seconds)} by 10% {when} ({_duration(t.focus_seconds * 1.1)})."


def build_report_data(db: Session, user: User, report_type: str, first: date, last: date) -> ReportData:
    d = get_dashboard(db, user, "custom", start_date=first, end_date=last)
    t = d.totals
    detected = [x for x in d.top_distractions if x.time_lost_seconds or x.source in ("screen", "camera")]
    top_source = max(detected or d.top_distractions, key=lambda x: (x.time_lost_seconds, x.count), default=None)
    top = (
        ReportDistraction(
            subject=top_source.subject, count=top_source.count, time_lost_seconds=top_source.time_lost_seconds
        )
        if top_source
        else None
    )
    screen_total = d.screen_time.focus + d.screen_time.neutral + d.screen_time.distracting
    on_task = round(d.screen_time.focus / screen_total, 3) if screen_total else None
    best = _best_session(db, user, first, last)

    score = f", focus score {t.average_focus_score:.0f}" if t.average_focus_score is not None else ""
    summary = (
        f"{_duration(t.focus_seconds)} focused across {t.sessions} session{'s' if t.sessions != 1 else ''}{score}, "
        f"{t.distractions} distraction{'s' if t.distractions != 1 else ''}."
    )
    return ReportData(
        title=_title(report_type, first, last),
        summary=summary,
        totals=ReportTotals(
            focus_seconds=t.focus_seconds,
            sessions=t.sessions,
            average_focus_score=t.average_focus_score,
            distractions=t.distractions,
            time_lost_seconds=t.time_lost_seconds,
        ),
        previous=ReportComparison(
            focus_seconds=d.previous.focus_seconds,
            distractions=d.previous.distractions,
            average_focus_score=d.previous.average_focus_score,
        ),
        goal_seconds=d.daily_goal_seconds,
        days_goal_met=sum(day.goal_met for day in d.days),
        days=[ReportDay(date=day.date, focus_seconds=day.focus_seconds, goal_met=day.goal_met) for day in d.days],
        tags=[ReportTag(name=x.name, color=x.color, focus_seconds=x.focus_seconds) for x in d.tags[:5]],
        top_distraction=top,
        best_session=best,
        on_task_share=on_task,
        highlights=_highlights(report_type, d, best, on_task),
        next_goal=_next_goal(report_type, d, top),
    )


def _save_report(db: Session, user: User, report_type: str, first: date, last: date) -> ReportLog | None:
    """Insert a report unless one exists for that period or nothing happened in it. Returns the new row."""
    exists = db.scalar(
        select(ReportLog.id).where(
            ReportLog.user_id == user.id, ReportLog.report_type == report_type, ReportLog.period_start == first
        )
    )
    if exists is not None or not _has_activity(db, user, first, last):
        return None
    data = build_report_data(db, user, report_type, first, last)
    stmt = (
        insert(ReportLog)
        .values(
            user_id=user.id,
            report_type=report_type,
            period_start=first,
            period_end=last,
            content=f"{data.title}: {data.summary}",
            data=data.model_dump(mode="json"),
        )
        .on_conflict_do_nothing(constraint="uq_report_logs_user_type_period")
        .returning(ReportLog.id)
    )
    # RETURNING yields no row when a concurrent generator inserted the same period first.
    report_id = db.execute(stmt).scalar()
    return db.get(ReportLog, report_id) if report_id is not None else None


def generate_due_reports_for_user(db: Session, user: User, at: datetime | None = None) -> list[ReportLog]:
    """Create the daily report for the user's local yesterday and the weekly one for their last full week.

    Safe to call any number of times: existing periods, empty periods, and periods before the account
    existed are skipped. Does not commit.
    """
    zone = ZoneInfo(user.timezone)
    today = (at or now_utc()).astimezone(zone).date()
    signup_day = user.created_at.astimezone(zone).date() if user.created_at else today

    created: list[ReportLog] = []
    yesterday = today - timedelta(days=1)
    if yesterday >= signup_day and (report := _save_report(db, user, "daily", yesterday, yesterday)):
        created.append(report)
    last_week_end = today - timedelta(days=today.weekday() + 1)  # the Sunday before this week
    last_week_start = last_week_end - timedelta(days=6)
    if last_week_end >= signup_day and (report := _save_report(db, user, "weekly", last_week_start, last_week_end)):
        created.append(report)
    return created


def generate_due_reports(at: datetime | None = None) -> int:
    """Scheduler entry point: generate any missing reports for every user and announce them."""
    created_total = 0
    with SessionLocal() as db:
        for user in db.scalars(select(User)):
            created = generate_due_reports_for_user(db, user, at)
            db.commit()
            for report in created:
                # The UI shows a toast and the desktop app a notification.
                payload = ReportLogResponse.model_validate(report).model_dump(mode="json")
                publish_user_event(user.id, "report.created", {"report": payload})
            created_total += len(created)
    if created_total:
        logger.info("generated %s report(s)", created_total)
    return created_total


def get_report(db: Session, user: User, report_id: int) -> ReportLog:
    report = db.get(ReportLog, report_id)
    if report is None or report.user_id != user.id:
        raise NotFoundError("Report not found")
    return report


def list_reports(
    db: Session,
    user: User,
    report_type: str | None,
    limit: int,
    offset: int,
    start_date: date | None,
    end_date: date | None,
) -> tuple[list[ReportLog], int]:
    filters = [ReportLog.user_id == user.id]
    if report_type:
        filters.append(ReportLog.report_type == report_type)
    # Filter on the period a report covers, not when it was written.
    if start_date:
        filters.append(ReportLog.period_end >= start_date)
    if end_date:
        filters.append(ReportLog.period_start <= end_date)

    items = db.scalars(
        select(ReportLog)
        .where(*filters)
        .order_by(ReportLog.period_start.desc(), ReportLog.report_type)
        .limit(limit)
        .offset(offset)
    )
    total = db.scalar(select(func.count(ReportLog.id)).where(*filters)) or 0
    return list(items), int(total)
