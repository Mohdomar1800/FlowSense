"""Focus score, distraction auto-attach, analytics on running sessions, and WebSocket live updates."""

from datetime import timedelta

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.events import LocalBroker, RedisBroker, set_broker
from app.core.timeutils import now_utc
from app.services.focus import compute_focus_score
from tests.conftest import API, login_headers, register
from tests.helpers import iso, log_distraction, make_session

# --- focus score ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("focus", "paused", "distractions", "expected"),
    [
        (3600, 0, 0, 100),  # clean hour
        (3600, 0, 2, 80),  # 2 distractions/hour -> -20
        (3600, 0, 10, 40),  # capped at -60
        (1800, 0, 1, 80),  # 1 in 30 min = 2/hour
        (60, 0, 1, 60),  # very short sessions use a 15-minute floor: 1 / 0.25h = 4/hour -> -40
        (3000, 600, 0, 93),  # 1/6 paused -> -6.7
        (600, 3000, 0, 80),  # mostly paused: pause penalty capped at -20
        (0, 0, 0, 100),
    ],
)
def test_focus_score_formula(focus, paused, distractions, expected):
    assert compute_focus_score(focus, paused, distractions) == expected


def test_score_is_stored_on_stop_and_updated_by_late_distractions(client, auth):
    start = now_utc() - timedelta(hours=2)
    session = make_session(client, auth, start, start + timedelta(hours=1))
    assert session["focus_score"] == 100

    log_distraction(client, auth, start + timedelta(minutes=10), session_id=session["id"])
    detail = client.get(f"{API}/sessions/{session['id']}", headers=auth).json()
    assert detail["focus_score"] == 90
    assert detail["distraction_count"] == 1


# --- distractions attach to the running session --------------------------------------------------


def test_distraction_auto_attaches_to_running_session(client, auth):
    session = client.post(
        f"{API}/sessions/start", headers=auth, json={"start_time": iso(now_utc() - timedelta(minutes=10))}
    ).json()
    distraction = client.post(f"{API}/distractions/manual", headers=auth, json={"reason": "Phone"}).json()
    assert distraction["session_id"] == session["id"]

    active = client.get(f"{API}/sessions/active", headers=auth).json()
    assert active["distraction_count"] == 1
    assert active["focus_score"] < 100


def test_distraction_before_running_session_stays_unattached(client, auth):
    start = now_utc() - timedelta(minutes=10)
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(start)})
    earlier = log_distraction(client, auth, start - timedelta(minutes=5))
    assert earlier["session_id"] is None


# --- analytics include running sessions ------------------------------------------------------------


def test_analytics_count_running_session_and_skip_cache(client, auth, cache):
    finished_start = now_utc() - timedelta(hours=3)
    make_session(client, auth, finished_start, finished_start + timedelta(minutes=30))
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(now_utc() - timedelta(minutes=20))})

    overview = client.get(f"{API}/analytics/productivity", headers=auth, params={"period": "month"}).json()["overview"]
    assert 50 * 60 - 5 <= overview["total_focus_seconds"] <= 50 * 60 + 5
    assert overview["focus_sessions_count"] == 2
    assert overview["average_focus_score"] == 100.0  # only the finished session has a final score
    assert cache.store == {}  # live numbers are not cached

    client.post(f"{API}/sessions/stop", headers=auth)
    client.get(f"{API}/analytics/productivity", headers=auth, params={"period": "month"})
    assert len(cache.store) == 1  # cached again once nothing is running


# --- WebSocket ------------------------------------------------------------------------------------


def _token(headers: dict) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


def test_websocket_rejects_bad_token(client):
    with client.websocket_connect(f"{API}/ws?token=nonsense") as ws, pytest.raises(WebSocketDisconnect) as exc:
        ws.receive_json()
    assert exc.value.code == 4401


def test_websocket_snapshot_and_live_events(client, auth):
    with client.websocket_connect(f"{API}/ws?token={_token(auth)}") as ws:
        assert ws.receive_json() == {"type": "snapshot", "session": None}

        started = client.post(f"{API}/sessions/start", headers=auth, json={}).json()
        event = ws.receive_json()
        assert event["type"] == "session.updated"
        assert event["session"]["id"] == started["id"]
        assert event["session"]["status"] == "active"

        client.post(f"{API}/distractions/manual", headers=auth, json={"reason": "Phone"})
        assert ws.receive_json()["type"] == "distraction.logged"
        assert ws.receive_json()["session"]["distraction_count"] == 1

        client.post(f"{API}/sessions/pause", headers=auth)
        assert ws.receive_json()["session"]["status"] == "paused"

        client.post(f"{API}/sessions/stop", headers=auth)
        assert ws.receive_json()["session"]["status"] == "ended"

        client.delete(f"{API}/sessions/{started['id']}", headers=auth)
        assert ws.receive_json() == {"type": "session.deleted", "session_id": started["id"]}

        ws.send_text("ping")
        assert ws.receive_text() == "pong"


def test_websocket_snapshot_includes_open_session(client, auth):
    started = client.post(f"{API}/sessions/start", headers=auth, json={"intent": "Reading"}).json()
    with client.websocket_connect(f"{API}/ws?token={_token(auth)}") as ws:
        snapshot = ws.receive_json()
        assert snapshot["session"]["id"] == started["id"]
        assert snapshot["session"]["intent"] == "Reading"


def _redis_available(url: str) -> bool:
    from redis import Redis
    from redis.exceptions import RedisError

    try:
        return bool(Redis.from_url(url, socket_connect_timeout=0.5).ping())
    except RedisError:
        return False


@pytest.mark.parametrize(
    "redis_url", ["redis://127.0.0.1:6379/0", "redis://127.0.0.1:1/0"], ids=["redis", "redis-down"]
)
def test_websocket_through_redis_broker(client, auth, redis_url):
    """Events flow through real Redis pub/sub, and fall back to in-process delivery when Redis is down."""
    if redis_url.endswith(":6379/0") and not _redis_available(redis_url):
        pytest.skip("Redis is not running")
    set_broker(RedisBroker(redis_url, LocalBroker()))

    with client.websocket_connect(f"{API}/ws?token={_token(auth)}") as ws:
        assert ws.receive_json()["type"] == "snapshot"
        started = client.post(f"{API}/sessions/start", headers=auth, json={}).json()
        assert ws.receive_json()["session"]["id"] == started["id"]


def test_websocket_only_receives_own_events(client, auth):
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    with client.websocket_connect(f"{API}/ws?token={_token(auth)}") as ws:
        ws.receive_json()  # snapshot
        client.post(f"{API}/sessions/start", headers=other, json={})  # someone else's event
        mine = client.post(f"{API}/sessions/start", headers=auth, json={}).json()
        assert ws.receive_json()["session"]["id"] == mine["id"]  # the first event received is ours
