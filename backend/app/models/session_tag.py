from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin


class SessionTag(TimestampMixin, Base):
    __tablename__ = "session_tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_session_tags_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6366f1", server_default="#6366f1")

    user = relationship("User", back_populates="tags")
    sessions = relationship("FocusSession", back_populates="tag")
