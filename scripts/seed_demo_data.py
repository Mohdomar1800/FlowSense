"""Seed demo data for FlowSense interview/demo environments.

Run:
    python scripts/seed_demo_data.py
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.base import SessionLocal
from app.models.distraction_event import DistractionEvent, DistractionType
from app.models.focus_session import FocusSession
from app.models.session_tag import SessionTag
from app.models.user import User
from app.services.security import hash_password


def seed() -> None:
    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.email == "demo@flowsense.local"))
        if existing:
            print("Demo user already exists; skipping seed")
            return

        demo_user = User(
            email="demo@flowsense.local",
            hashed_password=hash_password("demo-password"),
            timezone="UTC",
        )
        db.add(demo_user)
        db.flush()

        coding_tag = SessionTag(user_id=demo_user.id, name="coding")
        study_tag = SessionTag(user_id=demo_user.id, name="studying")
        db.add_all([coding_tag, study_tag])
        db.flush()

        now = datetime.now(UTC)
        sessions = [
            FocusSession(
                user_id=demo_user.id,
                tag_id=coding_tag.id,
                start_time=now - timedelta(days=2, hours=3),
                end_time=now - timedelta(days=2, hours=2, minutes=10),
                duration_seconds=50 * 60,
            ),
            FocusSession(
                user_id=demo_user.id,
                tag_id=study_tag.id,
                start_time=now - timedelta(days=1, hours=5),
                end_time=now - timedelta(days=1, hours=4, minutes=20),
                duration_seconds=40 * 60,
            ),
            FocusSession(
                user_id=demo_user.id,
                tag_id=coding_tag.id,
                start_time=now - timedelta(hours=4),
                end_time=now - timedelta(hours=3, minutes=15),
                duration_seconds=45 * 60,
            ),
        ]
        db.add_all(sessions)
        db.flush()

        distractions = [
            DistractionEvent(
                user_id=demo_user.id,
                session_id=sessions[0].id,
                event_type=DistractionType.MANUAL,
                reason="Checked phone",
                timestamp=sessions[0].start_time + timedelta(minutes=20),
            ),
            DistractionEvent(
                user_id=demo_user.id,
                session_id=sessions[2].id,
                event_type=DistractionType.INFERRED,
                reason="Inactivity detected",
                timestamp=sessions[2].start_time + timedelta(minutes=30),
            ),
        ]
        db.add_all(distractions)

        db.commit()
        print("Seed completed: demo@flowsense.local / demo-password")


if __name__ == "__main__":
    seed()
