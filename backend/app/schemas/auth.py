from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator


def _check_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Unknown timezone: {value}") from exc
    return value


def _check_password_length(value: str) -> str:
    # bcrypt only uses the first 72 bytes; reject longer passwords instead of silently truncating.
    if len(value.encode("utf-8")) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    timezone: str = Field(default="UTC", max_length=64)

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()

    _password = field_validator("password")(_check_password_length)
    _tz = field_validator("timezone")(_check_timezone)


class UserLogin(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def _lower_email(cls, value: str) -> str:
        return value.lower()


class UserUpdate(BaseModel):
    timezone: str | None = Field(default=None, max_length=64)
    # True marks the first-run setup as done (or skipped).
    onboarded: bool | None = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str | None) -> str | None:
        return _check_timezone(value) if value is not None else None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)

    _new = field_validator("new_password")(_check_password_length)


class AccountDeletion(BaseModel):
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    timezone: str
    onboarded_at: datetime | None = Field(exclude=True)

    @computed_field
    @property
    def onboarded(self) -> bool:
        return self.onboarded_at is not None
