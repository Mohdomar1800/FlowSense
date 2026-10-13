"""Seed demo data: a demo user with two weeks of sessions and distractions.

Run from backend/ after `alembic upgrade head`:
    python -m scripts.seed_demo_data            # create the demo user if it doesn't exist
    python -m scripts.seed_demo_data --reset    # recreate it, so the history ends yesterday again
"""

import argparse
import random
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.security import hash_password
from app.core.timeutils import now_utc
from app.db.session import SessionLocal
from app.models import (
    DistractionEvent,
    DistractionType,
    FocusSession,
    SessionEvent,
    SessionEventType,
    SessionStatus,
    SessionTag,
    User,
    UserSettings,
)
from app.services.focus import compute_focus_score
from app.services.report import generate_due_reports_for_user

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-password"
DISTRACTION_REASONS = ["Checked phone", "Opened social media", "Notification", "Chat message", "Snack break"]


def seed(days: int = 14, seed_value: int = 42, reset: bool = False) -> None:
    rng = random.Random(seed_value)
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.email == DEMO_EMAIL)):
            if not reset:
                print("Demo user already exists; skipping seed (use --reset to recreate it with fresh dates)")
                return
            # Sessions, tags, settings, reports etc. go with it (ON DELETE CASCADE).
            db.execute(delete(User).where(User.email == DEMO_EMAIL))
            print("Removed the old demo user")

        today = now_utc().replace(minute=0, second=0, microsecond=0)
        # Backdate the account to the first seeded day, so report generation covers the demo history.
        # Already onboarded: signing in goes straight to the Focus screen, not the setup wizard.
        created = today - timedelta(days=days + 1)
        user = User(
            email=DEMO_EMAIL,
            hashed_password=hash_password(DEMO_PASSWORD),
            timezone="UTC",
            created_at=created,
            onboarded_at=created,
        )
        user.settings = UserSettings()
        db.add(user)
        db.flush()

        tags = [
            SessionTag(user_id=user.id, name="coding", color="#6366f1"),
            SessionTag(user_id=user.id, name="studying", color="#10b981"),
            SessionTag(user_id=user.id, name="reading", color="#f59e0b"),
        ]
        db.add_all(tags)
        db.flush()

        for day_offset in range(days, 0, -1):
            day = today - timedelta(days=day_offset)
            for start_hour in rng.sample([8, 10, 13, 15, 19, 21], k=rng.randint(1, 3)):
                start = day.replace(hour=start_hour, minute=rng.choice([0, 10, 20, 30]))
                minutes = rng.randint(20, 75)
                paused_minutes = rng.choice([0, 0, 2, 4])
                end = start + timedelta(minutes=minutes + paused_minutes)
                session = FocusSession(
                    user_id=user.id,
                    tag_id=rng.choice(tags).id,
                    status=SessionStatus.ENDED,
                    start_time=start,
                    end_time=end,
                    paused_seconds=paused_minutes * 60,
                    duration_seconds=minutes * 60,
                )
                db.add(session)
                db.flush()
                events = [SessionEvent(session_id=session.id, event_type=SessionEventType.STARTED, timestamp=start)]
                if paused_minutes:
                    pause_start = start + timedelta(minutes=minutes // 2)
                    events += [
                        SessionEvent(session_id=session.id, event_type=SessionEventType.PAUSED, timestamp=pause_start),
                        SessionEvent(
                            session_id=session.id,
                            event_type=SessionEventType.RESUMED,
                            timestamp=pause_start + timedelta(minutes=paused_minutes),
                            details={"pause_seconds": paused_minutes * 60},
                        ),
                    ]
                events.append(SessionEvent(session_id=session.id, event_type=SessionEventType.STOPPED, timestamp=end))
                db.add_all(events)

                # Evening sessions get more distractions, so the insights have a pattern to find.
                distraction_count = rng.randint(0, 3 if start_hour >= 18 else 1)
                session.focus_score = compute_focus_score(
                    session.duration_seconds, session.paused_seconds, distraction_count
                )
                for _ in range(distraction_count):
                    inferred = rng.random() < 0.3
                    db.add(
                        DistractionEvent(
                            user_id=user.id,
                            session_id=session.id,
                            event_type=DistractionType.INFERRED if inferred else DistractionType.MANUAL,
                            reason="Inactive for 5 minutes" if inferred else rng.choice(DISTRACTION_REASONS),
                            inactive_minutes=5 if inferred else None,
                            timestamp=start + timedelta(minutes=rng.randint(1, minutes - 1)),
                        )
                    )

        db.commit()

        # Produce the reports the app would have generated each night over those days.
        for day_offset in range(days, -1, -1):
            generate_due_reports_for_user(db, user, at=today - timedelta(days=day_offset) + timedelta(hours=1))
        db.commit()
        print(f"Seed completed: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create the FlowSense demo user with two weeks of history")
    parser.add_argument("--reset", action="store_true", help="delete and recreate the demo user")
    seed(reset=parser.parse_args().reset)
