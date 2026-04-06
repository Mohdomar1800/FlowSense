from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class FocusSession(Base):
    __tablename__ = "focus_sessions"
    __table_args__ = (
        CheckConstraint("end_time IS NULL OR end_time >= start_time", name="ck_session_end_after_start"),
        Index("ix_focus_sessions_user_start_time", "user_id", "start_time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id: Mapped[int | None] = mapped_column(ForeignKey("session_tags.id", ondelete="SET NULL"), nullable=True, index=True)

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pause_threshold_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="sessions")
    tag = relationship("SessionTag", back_populates="sessions")
    distractions = relationship("DistractionEvent", back_populates="session", cascade="all, delete-orphan")
