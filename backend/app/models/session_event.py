from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, func
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SessionEventType(str, Enum):
    STARTED = "started"
    PAUSED = "paused"
    RESUMED = "resumed"
    STOPPED = "stopped"


class SessionEvent(Base):
    """Lifecycle history of a focus session. Distractions live in their own table and are merged into the timeline."""

    __tablename__ = "session_events"
    __table_args__ = (Index("ix_session_events_session_timestamp", "session_id", "timestamp"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("focus_sessions.id", ondelete="CASCADE"), nullable=False)
    event_type: Mapped[SessionEventType] = mapped_column(
        SQLEnum(SessionEventType, name="session_event_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Extra context, e.g. {"reason": "long_pause"} or {"split_from": 12}.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    session = relationship("FocusSession", back_populates="events")
