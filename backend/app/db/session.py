from collections.abc import Callable, Generator
from contextlib import AbstractContextManager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

# Small pool: FlowSense is mostly a single-user local app, and every idle connection costs Postgres memory.
engine = create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=5)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session_factory() -> Callable[[], AbstractContextManager[Session]]:
    """For long-lived handlers (WebSockets) that should borrow a connection briefly rather than hold one open."""
    return SessionLocal


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
