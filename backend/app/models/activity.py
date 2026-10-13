from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ActivityCategory(str, Enum):
    FOCUS = "focus"
    NEUTRAL = "neutral"
    DISTRACTING = "distracting"


class RuleKind(str, Enum):
    FOCUS = "focus"
    DISTRACTION = "distraction"


class ActivityRule(Base):
    """A user's own "always allow" / "always block" rule for screen activity."""

    __tablename__ = "activity_rules"
    __table_args__ = (UniqueConstraint("user_id", "pattern", name="uq_activity_rules_user_pattern"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # Lowercase text matched anywhere in "app | window title".
    pattern: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[RuleKind] = mapped_column(
        SQLEnum(RuleKind, name="rule_kind", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class ActivitySegment(Base):
    """A continuous stretch of time on one window during a focus session."""

    __tablename__ = "activity_segments"
    __table_args__ = (
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="end_after_start"),
        Index("ix_activity_segments_user_started", "user_id", "started_at"),
        # At most one open segment per user.
        Index("uq_activity_segments_one_open", "user_id", unique=True, postgresql_where=text("ended_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("focus_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    app: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    subject: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[ActivityCategory] = mapped_column(
        SQLEnum(ActivityCategory, name="activity_category", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
