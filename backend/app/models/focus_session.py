from datetime import datetime
from enum import Enum

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SessionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class FocusSession(TimestampMixin, Base):
    __tablename__ = "focus_sessions"
    __table_args__ = (
        CheckConstraint("end_time IS NULL OR end_time >= start_time", name="end_after_start"),
        CheckConstraint("duration_seconds >= 0", name="duration_non_negative"),
        CheckConstraint("paused_seconds >= 0", name="paused_non_negative"),
        CheckConstraint("focus_score IS NULL OR focus_score BETWEEN 0 AND 100", name="focus_score_range"),
        # Status and timestamps must agree: only ended sessions have an end, only paused ones have a pause start.
        CheckConstraint(
            "(status = 'ended') = (end_time IS NOT NULL) AND (status = 'paused') = (paused_at IS NOT NULL)",
            name="status_consistent",
        ),
        Index("ix_focus_sessions_user_start_time", "user_id", "start_time"),
        # At most one unfinished (active or paused) session per user, enforced even under concurrent requests.
        Index(
            "uq_focus_sessions_one_active_per_user",
            "user_id",
            unique=True,
            postgresql_where=text("end_time IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[int | None] = mapped_column(
        ForeignKey("session_tags.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # What the user said they are working on; later used to judge whether on-screen activity is on-task.
    intent: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[SessionStatus] = mapped_column(
        SQLEnum(SessionStatus, name="session_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=SessionStatus.ACTIVE,
        server_default=SessionStatus.ACTIVE.value,
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set while paused: when the current pause began.
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Total seconds spent in completed pauses.
    paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Focused time (wall time minus pauses). Final once ended; for open sessions the live value is computed.
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    focus_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Snapshot of the user's setting when the session started.
    pause_threshold_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")

    user = relationship("User", back_populates="sessions")
    tag = relationship("SessionTag", back_populates="sessions")
    distractions = relationship("DistractionEvent", back_populates="session")
    events = relationship(
        "SessionEvent", back_populates="session", cascade="all, delete-orphan", order_by="SessionEvent.timestamp"
    )
