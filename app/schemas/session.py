from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SessionStartRequest(BaseModel):
    tag_id: int | None = None
    start_time: datetime | None = None


class SessionStopRequest(BaseModel):
    end_time: datetime | None = None


class SessionPauseRequest(BaseModel):
    paused_at: datetime
    resumed_at: datetime


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    tag_id: int | None
    start_time: datetime
    end_time: datetime | None
    duration_seconds: int
    pause_threshold_seconds: int


class SessionListQuery(BaseModel):
    period: Literal["day", "week", "month", "custom"] = "day"
    reference_date: date | None = None
    start_date: date | None = None
    end_date: date | None = None


class SessionSummary(BaseModel):
    sessions: list[SessionResponse]
    total_focus_seconds: int = Field(ge=0)
