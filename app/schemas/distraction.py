from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class DistractionCreateRequest(BaseModel):
    session_id: int | None = None
    reason: str | None = Field(default=None, max_length=255)
    timestamp: datetime | None = None


class InferredDistractionRequest(BaseModel):
    session_id: int | None = None
    inactive_minutes: int = Field(ge=1, le=180)
    reason: str | None = Field(default="Inferred due to inactivity", max_length=255)
    timestamp: datetime | None = None


class DistractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    session_id: int | None
    event_type: str
    reason: str | None
    timestamp: datetime


class DistractionListResponse(BaseModel):
    items: list[DistractionResponse]
    total_count: int


class DistractionSummaryResponse(BaseModel):
    day: date
    total_events: int
    manual_events: int
    inferred_events: int
