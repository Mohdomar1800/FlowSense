from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class DistractionType(str, Enum):
    MANUAL = "manual"  # the user pressed "I got distracted"
    INFERRED = "inferred"  # no keyboard/mouse input for a while
    SCREEN = "screen"  # an off-task app or site on screen
    CAMERA = "camera"  # phone use seen by the camera


class DistractionEvent(TimestampMixin, Base):
    __tablename__ = "distraction_events"
    __table_args__ = (
        Index("ix_distraction_events_user_timestamp", "user_id", "timestamp"),
        CheckConstraint("duration_seconds IS NULL OR duration_seconds >= 0", name="duration_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("focus_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # When the distraction began.
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[DistractionType] = mapped_column(
        SQLEnum(DistractionType, name="distraction_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # What distracted the user, in short form ("YouTube", "Phone"); used for stats and "always allow".
    subject: Mapped[str | None] = mapped_column(String(120), nullable=True)
    inactive_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # How long it lasted, once the user is back on task (screen/camera distractions).
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)

    user = relationship("User", back_populates="distractions")
    session = relationship("FocusSession", back_populates="distractions")
