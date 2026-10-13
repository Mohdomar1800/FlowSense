from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.activity import ActivityCategory, RuleKind


class ActivityReport(BaseModel):
    """Sent by the desktop agent whenever the foreground window changes."""

    app: str = Field(max_length=500)
    title: str = Field(default="", max_length=2000)
    at: datetime | None = None


class ActivityResult(BaseModel):
    category: ActivityCategory
    subject: str
    reason: str
    # False when no session is running: the window was classified but not recorded.
    tracked: bool


class RuleCreate(BaseModel):
    pattern: str = Field(min_length=2, max_length=120)
    kind: RuleKind

    @field_validator("pattern")
    @classmethod
    def _normalize(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) < 2:
            raise ValueError("Pattern must be at least 2 characters")
        return value


class RuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    pattern: str
    kind: RuleKind
    created_at: datetime
