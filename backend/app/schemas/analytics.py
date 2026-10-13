from datetime import date

from pydantic import BaseModel


class TagFocusStat(BaseModel):
    tag_id: int | None
    tag_name: str | None
    total_focus_seconds: int


class HourlyDistractionStat(BaseModel):
    hour: int  # 0-23 in the user's timezone
    distraction_count: int


class ProductivityOverview(BaseModel):
    period: str
    start_date: date
    end_date: date
    total_focus_seconds: int
    total_distractions: int
    average_session_seconds: float
    focus_sessions_count: int
    # Mean score of finished sessions in the period; None when there are none.
    average_focus_score: float | None


class ProductivityAnalyticsResponse(BaseModel):
    overview: ProductivityOverview
    focus_by_tag: list[TagFocusStat]
    distractions_by_hour: list[HourlyDistractionStat]
