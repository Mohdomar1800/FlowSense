from datetime import date

from pydantic import BaseModel


class DashboardTotals(BaseModel):
    focus_seconds: int
    sessions: int
    average_session_seconds: float
    # Mean score of finished sessions; None when none finished in the period.
    average_focus_score: float | None
    distractions: int
    # Sum of measured distraction durations (screen/camera episodes).
    time_lost_seconds: int


class DashboardComparison(BaseModel):
    """Same-length period immediately before, for "vs last week" style deltas."""

    start_date: date
    end_date: date
    focus_seconds: int
    distractions: int
    average_focus_score: float | None


class DayStat(BaseModel):
    date: date
    focus_seconds: int
    sessions: int
    distractions: int
    average_focus_score: float | None
    goal_met: bool


class HourStat(BaseModel):
    hour: int  # 0-23, user's local time
    focus_seconds: int
    distractions: int


class HeatCell(BaseModel):
    weekday: int  # 0 = Monday
    hour: int
    focus_seconds: int


class TagStat(BaseModel):
    tag_id: int | None
    name: str
    color: str
    focus_seconds: int


class DistractionStat(BaseModel):
    subject: str
    source: str  # manual | inferred | screen | camera
    count: int
    time_lost_seconds: int


class ActivityStat(BaseModel):
    subject: str
    category: str  # focus | neutral | distracting
    seconds: int


class CategoryTime(BaseModel):
    focus: int
    neutral: int
    distracting: int


class DashboardResponse(BaseModel):
    period: str
    start_date: date
    end_date: date
    daily_goal_seconds: int
    totals: DashboardTotals
    previous: DashboardComparison
    days: list[DayStat]
    hours: list[HourStat]
    heatmap: list[HeatCell]
    tags: list[TagStat]
    top_distractions: list[DistractionStat]
    screen_time: CategoryTime
    top_activities: list[ActivityStat]
