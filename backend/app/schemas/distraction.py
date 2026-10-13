from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.distraction_event import DistractionType


class DistractionCreateRequest(BaseModel):
    session_id: int | None = None
    reason: str | None = Field(default=None, max_length=255)
    timestamp: datetime | None = None


class InferredDistractionRequest(BaseModel):
    session_id: int | None = None
    inactive_minutes: int = Field(ge=1, le=180)
    reason: str | None = Field(default=None, max_length=255)
    timestamp: datetime | None = None


class DetectedDistractionRequest(BaseModel):
    """Sent by the desktop app when it notices a distraction (screen now, camera later)."""

    source: Literal["screen", "camera"]
    subject: str = Field(min_length=1, max_length=120)
    reason: str | None = Field(default=None, max_length=255)
    # When the distraction began (before the grace period ran out).
    timestamp: datetime | None = None


class DistractionEndRequest(BaseModel):
    at: datetime | None = None


class DistractionDismissRequest(BaseModel):
    always_allow: bool = False


class DistractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    session_id: int | None
    event_type: DistractionType
    reason: str | None
    subject: str | None
    inactive_minutes: int | None
    duration_seconds: int | None
    timestamp: datetime


class DistractionListResponse(BaseModel):
    items: list[DistractionResponse]
    total_count: int


class DistractionSummaryResponse(BaseModel):
    day: date
    total_events: int
    manual_events: int
    inferred_events: int
    screen_events: int
    camera_events: int
