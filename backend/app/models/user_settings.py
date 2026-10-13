from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class UserSettings(TimestampMixin, Base):
    """Per-user preferences. One row per user, created at registration."""

    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("pause_threshold_seconds BETWEEN 30 AND 7200", name="pause_threshold_range"),
        CheckConstraint("daily_focus_goal_minutes BETWEEN 0 AND 1440", name="daily_goal_range"),
        CheckConstraint("distraction_grace_seconds BETWEEN 0 AND 600", name="grace_range"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # A pause longer than this ends the current session and starts a new one on resume.
    pause_threshold_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    daily_focus_goal_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=120, server_default="120")
    # How long off-task activity must last before it counts as a distraction.
    distraction_grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15, server_default="15")
    screen_tracking_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    camera_tracking_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )

    user = relationship("User", back_populates="settings")
