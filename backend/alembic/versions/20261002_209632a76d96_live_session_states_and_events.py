"""live session states and events

Adds session status/pause tracking, focus score, intent, and the session_events history table.
Existing sessions are backfilled: finished ones become 'ended' with a 'started' and 'stopped' event.

Revision ID: 209632a76d96
Revises: 2f1992c9c655
Create Date: 2026-10-02 16:52:28.040820
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "209632a76d96"
down_revision: str | None = "2f1992c9c655"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

session_status = postgresql.ENUM("active", "paused", "ended", name="session_status", create_type=False)
session_event_type = postgresql.ENUM(
    "started", "paused", "resumed", "stopped", name="session_event_type", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    session_status.create(bind, checkfirst=True)
    session_event_type.create(bind, checkfirst=True)

    op.add_column("focus_sessions", sa.Column("intent", sa.String(length=200), nullable=True))
    op.add_column("focus_sessions", sa.Column("status", session_status, server_default="active", nullable=False))
    op.add_column("focus_sessions", sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("focus_sessions", sa.Column("paused_seconds", sa.Integer(), server_default="0", nullable=False))
    op.add_column("focus_sessions", sa.Column("focus_score", sa.Integer(), nullable=True))

    # Backfill before the consistency check is added.
    op.execute("UPDATE focus_sessions SET status = 'ended' WHERE end_time IS NOT NULL")

    op.create_check_constraint("ck_focus_sessions_paused_non_negative", "focus_sessions", "paused_seconds >= 0")
    op.create_check_constraint(
        "ck_focus_sessions_focus_score_range", "focus_sessions", "focus_score IS NULL OR focus_score BETWEEN 0 AND 100"
    )
    op.create_check_constraint(
        "ck_focus_sessions_status_consistent",
        "focus_sessions",
        "(status = 'ended') = (end_time IS NOT NULL) AND (status = 'paused') = (paused_at IS NOT NULL)",
    )

    op.create_table(
        "session_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("event_type", session_event_type, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["focus_sessions.id"],
            name=op.f("fk_session_events_session_id_focus_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session_events")),
    )
    op.create_index("ix_session_events_session_timestamp", "session_events", ["session_id", "timestamp"], unique=False)

    op.execute(
        "INSERT INTO session_events (session_id, event_type, timestamp) "
        "SELECT id, 'started', start_time FROM focus_sessions"
    )
    op.execute(
        "INSERT INTO session_events (session_id, event_type, timestamp) "
        "SELECT id, 'stopped', end_time FROM focus_sessions WHERE end_time IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_session_events_session_timestamp", table_name="session_events")
    op.drop_table("session_events")
    op.drop_constraint("ck_focus_sessions_status_consistent", "focus_sessions", type_="check")
    op.drop_constraint("ck_focus_sessions_focus_score_range", "focus_sessions", type_="check")
    op.drop_constraint("ck_focus_sessions_paused_non_negative", "focus_sessions", type_="check")
    op.drop_column("focus_sessions", "focus_score")
    op.drop_column("focus_sessions", "paused_seconds")
    op.drop_column("focus_sessions", "paused_at")
    op.drop_column("focus_sessions", "status")
    op.drop_column("focus_sessions", "intent")
    bind = op.get_bind()
    session_event_type.drop(bind, checkfirst=True)
    session_status.drop(bind, checkfirst=True)
