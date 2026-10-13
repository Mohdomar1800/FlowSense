from datetime import date, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class ReportLog(Base):
    __tablename__ = "report_logs"
    __table_args__ = (
        CheckConstraint("report_type IN ('daily', 'weekly')", name="report_type_valid"),
        # One report per user, type and period: makes generation idempotent and safe to retry.
        UniqueConstraint("user_id", "report_type", "period_start", name="uq_report_logs_user_type_period"),
        Index("ix_report_logs_user_period", "user_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # Local calendar dates (in the user's timezone) the report covers, inclusive.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    # One-paragraph summary (shown in lists and notifications).
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # The full recap as a snapshot (see schemas.report.ReportData). Null for reports from before it existed.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="reports")
