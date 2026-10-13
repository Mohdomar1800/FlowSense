from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ReportTotals(BaseModel):
    focus_seconds: int
    sessions: int
    average_focus_score: float | None
    distractions: int
    time_lost_seconds: int


class ReportComparison(BaseModel):
    focus_seconds: int
    distractions: int
    average_focus_score: float | None


class BestSession(BaseModel):
    start_time: datetime
    focus_seconds: int
    focus_score: int | None
    label: str  # intent, else tag name, else "Focus session"


class ReportDay(BaseModel):
    date: date
    focus_seconds: int
    goal_met: bool


class ReportTag(BaseModel):
    name: str
    color: str
    focus_seconds: int


class ReportDistraction(BaseModel):
    subject: str
    count: int
    time_lost_seconds: int


class ReportData(BaseModel):
    """A frozen recap of one day or week."""

    title: str
    summary: str
    totals: ReportTotals
    previous: ReportComparison
    goal_seconds: int
    days_goal_met: int
    days: list[ReportDay]
    tags: list[ReportTag]
    top_distraction: ReportDistraction | None
    best_session: BestSession | None
    on_task_share: float | None  # share of tracked screen time that was on task (0-1)
    highlights: list[str]
    next_goal: str


class ReportLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    report_type: str
    period_start: date
    period_end: date
    content: str
    data: ReportData | None
    created_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportLogResponse]
    total_count: int
