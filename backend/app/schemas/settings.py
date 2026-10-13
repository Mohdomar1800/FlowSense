from pydantic import BaseModel, ConfigDict, Field


class SettingsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    pause_threshold_seconds: int
    daily_focus_goal_minutes: int
    distraction_grace_seconds: int
    screen_tracking_enabled: bool
    camera_tracking_enabled: bool


class SettingsUpdate(BaseModel):
    pause_threshold_seconds: int | None = Field(default=None, ge=30, le=7200)
    daily_focus_goal_minutes: int | None = Field(default=None, ge=0, le=1440)
    distraction_grace_seconds: int | None = Field(default=None, ge=0, le=600)
    screen_tracking_enabled: bool | None = None
    camera_tracking_enabled: bool | None = None
