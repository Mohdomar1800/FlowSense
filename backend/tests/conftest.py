import os

# Configure the app for tests before anything imports app settings.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://flowsense:flowsense@127.0.0.1:5432/flowsense_test"
)
os.environ["DATABASE_URL_OVERRIDE"] = TEST_DATABASE_URL
os.environ["SCHEDULER_ENABLED"] = "false"
os.environ["REDIS_ENABLED"] = "false"
os.environ["JWT_SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"
os.environ["BCRYPT_ROUNDS"] = "4"

from collections.abc import Iterator  # noqa: E402
from contextlib import nullcontext  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from app.core.cache import InMemoryCache, set_cache  # noqa: E402
from app.core.events import LocalBroker, set_broker  # noqa: E402
from app.core.ratelimit import login_limiter  # noqa: E402
from app.db.session import engine, get_db, get_session_factory  # noqa: E402
from app.main import app  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _recreate_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{url.database}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()


@pytest.fixture(scope="session", autouse=True)
def _database() -> Iterator[None]:
    """Fresh database per test run, built through the real migrations."""
    _recreate_test_database()
    config = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DATABASE_URL)
    command.upgrade(config, "head")
    yield
    engine.dispose()


@pytest.fixture
def db() -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back afterwards; service commits become savepoints."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def cache() -> InMemoryCache:
    memory_cache = InMemoryCache()
    set_cache(memory_cache)
    return memory_cache


@pytest.fixture
def broker() -> LocalBroker:
    local_broker = LocalBroker()
    set_broker(local_broker)
    return local_broker


@pytest.fixture
def client(db: Session, cache: InMemoryCache, broker: LocalBroker) -> Iterator[TestClient]:
    login_limiter._memory.clear()  # module-level state: don't let one test's failed logins leak into another
    app.dependency_overrides[get_db] = lambda: db
    # WebSocket handlers borrow sessions from a factory; hand them the test transaction's session.
    app.dependency_overrides[get_session_factory] = lambda: (lambda: nullcontext(db))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


API = "/api/v1"


def register(client: TestClient, email: str = "user@example.com", password: str = "password123", timezone: str = "UTC"):
    response = client.post(f"{API}/auth/register", json={"email": email, "password": password, "timezone": timezone})
    assert response.status_code == 201, response.text
    return response.json()


def login_headers(client: TestClient, email: str = "user@example.com", password: str = "password123") -> dict:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth(client: TestClient) -> dict:
    """Headers for a freshly registered UTC user."""
    register(client)
    return login_headers(client)
