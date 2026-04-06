from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, Enum as SQLEnum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DistractionType(str, Enum):
    MANUAL = "manual"
    INFERRED = "inferred"


class DistractionEvent(Base):
    __tablename__ = "distraction_events"
    __table_args__ = (Index("ix_distraction_events_user_timestamp", "user_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("focus_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    event_type: Mapped[DistractionType] = mapped_column(SQLEnum(DistractionType, name="distractiontype"), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user = relationship("User", back_populates="distractions")
    session = relationship("FocusSession", back_populates="distractions")
