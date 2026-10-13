from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.models.focus_session import SessionStatus


def _clean_intent(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


class SessionStartRequest(BaseModel):
    tag_id: int | None = None
    intent: str | None = Field(default=None, max_length=200)
    # Optional explicit times (backfilling, tests). Defaults to now.
    start_time: datetime | None = None

    _intent = field_validator("intent")(_clean_intent)


class SessionActionRequest(BaseModel):
    """Body for pause/resume/stop. `at` defaults to now."""

    at: datetime | None = None


class SessionUpdateRequest(BaseModel):
    tag_id: int | None = None
    intent: str | None = Field(default=None, max_length=200)

    _intent = field_validator("intent")(_clean_intent)


class SessionResponse(BaseModel):
    id: int
    user_id: int
    tag_id: int | None
    intent: str | None
    status: SessionStatus
    start_time: datetime
    end_time: datetime | None
    paused_at: datetime | None
    paused_seconds: int
    # Focused seconds so far (live for open sessions).
    duration_seconds: int
    distraction_count: int
    # Final for ended sessions; a live estimate for open ones.
    focus_score: int
    pause_threshold_seconds: int


class SessionTransitionResponse(BaseModel):
    """Result of a resume: `previous_session` is set when a long pause split the session in two."""

    session: SessionResponse
    previous_session: SessionResponse | None = None
    split: bool = False


class TimelineItem(BaseModel):
    kind: Literal["started", "paused", "resumed", "stopped", "distraction"]
    timestamp: datetime
    details: dict[str, Any] | None = None


class SessionDetailResponse(SessionResponse):
    timeline: list[TimelineItem]


class SessionSummary(BaseModel):
    sessions: list[SessionResponse]
    total_focus_seconds: int = Field(ge=0)
