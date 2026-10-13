"""Screen activity reports, rules, segments and detected (screen) distractions."""

from datetime import timedelta

from app.core.timeutils import now_utc
from app.models import ActivitySegment
from tests.conftest import API, login_headers, register
from tests.helpers import iso

CHROME = "chrome.exe"


def _report(client, auth, app, title, at=None):
    body = {"app": app, "title": title}
    if at is not None:
        body["at"] = iso(at)
    response = client.post(f"{API}/activity", headers=auth, json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _start(client, auth, minutes_ago=30, intent=None):
    response = client.post(
        f"{API}/sessions/start",
        headers=auth,
        json={"start_time": iso(now_utc() - timedelta(minutes=minutes_ago)), "intent": intent},
    )
    assert response.status_code == 201
    return response.json()


# --- classification & segments --------------------------------------------------------------------


def test_activity_without_session_is_classified_but_not_recorded(client, auth, db):
    result = _report(client, auth, CHROME, "Instagram - Google Chrome")
    assert result == {
        "category": "distracting",
        "subject": "Instagram",
        "reason": "Instagram is usually a distraction",
        "tracked": False,
    }
    assert db.query(ActivitySegment).count() == 0


def test_activity_during_session_records_segments(client, auth, db):
    _start(client, auth)
    t0 = now_utc() - timedelta(minutes=20)
    _report(client, auth, "Code.exe", "main.py - Visual Studio Code", t0)
    _report(client, auth, CHROME, "Funny cats - YouTube - Google Chrome", t0 + timedelta(minutes=10))
    _report(client, auth, "Code.exe", "main.py - Visual Studio Code", t0 + timedelta(minutes=12))

    segments = db.query(ActivitySegment).order_by(ActivitySegment.started_at).all()
    assert [(s.subject, s.category.value, s.duration_seconds) for s in segments] == [
        ("Visual Studio Code", "focus", 600),
        ("YouTube", "distracting", 120),
        ("Visual Studio Code", "focus", 0),  # still open
    ]
    assert segments[-1].ended_at is None


def test_pause_and_stop_close_the_open_segment(client, auth, db):
    _start(client, auth)
    _report(client, auth, "Code.exe", "x - Visual Studio Code", now_utc() - timedelta(minutes=5))
    client.post(f"{API}/sessions/pause", headers=auth)
    segment = db.query(ActivitySegment).one()
    assert segment.ended_at is not None
    assert 295 <= segment.duration_seconds <= 305

    # While paused, windows are classified but not recorded.
    assert _report(client, auth, CHROME, "Reddit - Google Chrome")["tracked"] is False
    client.post(f"{API}/sessions/resume", headers=auth)
    _report(client, auth, "Code.exe", "x - Visual Studio Code")
    client.post(f"{API}/sessions/stop", headers=auth)
    assert db.query(ActivitySegment).filter(ActivitySegment.ended_at.is_(None)).count() == 0


def test_session_intent_is_used(client, auth):
    _start(client, auth, intent="Elden Ring essay")
    result = _report(client, auth, CHROME, "Elden Ring lore explained - YouTube - Google Chrome")
    assert result["category"] == "focus"
    assert "Matches what you're working on" in result["reason"]


def test_long_titles_are_truncated_not_rejected(client, auth, db):
    _start(client, auth)
    _report(client, auth, "x" * 300, "y" * 1500)
    segment = db.query(ActivitySegment).one()
    assert len(segment.app) == 120 and len(segment.title) == 300


# --- rules ----------------------------------------------------------------------------------------


def test_rules_crud_and_effect(client, auth):
    assert _report(client, auth, "Discord.exe", "Study group - Discord")["category"] == "distracting"

    created = client.post(f"{API}/activity/rules", headers=auth, json={"pattern": "  Discord ", "kind": "focus"})
    assert created.status_code == 201
    assert created.json()["pattern"] == "discord"
    assert (
        client.post(f"{API}/activity/rules", headers=auth, json={"pattern": "discord", "kind": "focus"}).status_code
        == 409
    )
    assert client.post(f"{API}/activity/rules", headers=auth, json={"pattern": "x", "kind": "focus"}).status_code == 422
    assert (
        client.post(f"{API}/activity/rules", headers=auth, json={"pattern": "abc", "kind": "maybe"}).status_code == 422
    )

    assert _report(client, auth, "Discord.exe", "Study group - Discord")["category"] == "focus"
    assert [r["pattern"] for r in client.get(f"{API}/activity/rules", headers=auth).json()] == ["discord"]

    assert client.delete(f"{API}/activity/rules/{created.json()['id']}", headers=auth).status_code == 204
    assert _report(client, auth, "Discord.exe", "Study group - Discord")["category"] == "distracting"


def test_rules_are_private(client, auth):
    rule = client.post(f"{API}/activity/rules", headers=auth, json={"pattern": "reddit", "kind": "focus"}).json()
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    assert client.get(f"{API}/activity/rules", headers=other).json() == []
    assert client.delete(f"{API}/activity/rules/{rule['id']}", headers=other).status_code == 404
    assert _report(client, other, CHROME, "Reddit - Google Chrome")["category"] == "distracting"


# --- detected distractions ------------------------------------------------------------------------


def _detect(client, auth, subject="YouTube", seconds_ago=20, reason="Funny cats - YouTube"):
    return client.post(
        f"{API}/distractions/detected",
        headers=auth,
        json={
            "source": "screen",
            "subject": subject,
            "reason": reason,
            "timestamp": iso(now_utc() - timedelta(seconds=seconds_ago)),
        },
    )


def test_detected_distraction_requires_running_session(client, auth):
    assert _detect(client, auth).status_code == 409


def test_detected_distraction_lifecycle(client, auth):
    session = _start(client, auth)
    response = _detect(client, auth)
    assert response.status_code == 201
    distraction = response.json()
    assert distraction["event_type"] == "screen"
    assert distraction["subject"] == "YouTube"
    assert distraction["session_id"] == session["id"]
    assert distraction["duration_seconds"] is None

    ended = client.post(f"{API}/distractions/{distraction['id']}/end", headers=auth, json={}).json()
    assert 18 <= ended["duration_seconds"] <= 25

    summary = client.get(f"{API}/distractions/summary/daily", headers=auth).json()
    assert summary["screen_events"] == 1 and summary["total_events"] == 1


def test_dismiss_removes_and_can_always_allow(client, auth):
    _start(client, auth)
    first = _detect(client, auth).json()
    assert client.post(f"{API}/distractions/{first['id']}/dismiss", headers=auth, json={}).status_code == 204
    assert client.get(f"{API}/distractions", headers=auth).json()["total_count"] == 0
    assert client.get(f"{API}/activity/rules", headers=auth).json() == []
    assert client.get(f"{API}/sessions/active", headers=auth).json()["distraction_count"] == 0

    second = _detect(client, auth, subject="Discord").json()
    assert (
        client.post(f"{API}/distractions/{second['id']}/dismiss", headers=auth, json={"always_allow": True}).status_code
        == 204
    )
    rules = client.get(f"{API}/activity/rules", headers=auth).json()
    assert [(r["pattern"], r["kind"]) for r in rules] == [("discord", "focus")]
    assert _report(client, auth, "Discord.exe", "General - Discord")["category"] == "focus"


def test_camera_distractions_can_be_dismissed_but_not_always_allowed(client, auth):
    _start(client, auth)
    phone = client.post(
        f"{API}/distractions/detected", headers=auth, json={"source": "camera", "subject": "Phone"}
    ).json()
    assert phone["event_type"] == "camera"
    allow = client.post(f"{API}/distractions/{phone['id']}/dismiss", headers=auth, json={"always_allow": True})
    assert allow.status_code == 400
    assert client.post(f"{API}/distractions/{phone['id']}/dismiss", headers=auth, json={}).status_code == 204
    assert client.get(f"{API}/activity/rules", headers=auth).json() == []

    summary = client.get(f"{API}/distractions/summary/daily", headers=auth).json()
    assert summary["camera_events"] == 0


def test_always_allow_overrides_an_existing_block_rule(client, auth):
    client.post(f"{API}/activity/rules", headers=auth, json={"pattern": "youtube", "kind": "distraction"})
    _start(client, auth)
    distraction = _detect(client, auth).json()
    client.post(f"{API}/distractions/{distraction['id']}/dismiss", headers=auth, json={"always_allow": True})
    assert [r["kind"] for r in client.get(f"{API}/activity/rules", headers=auth).json()] == ["focus"]


def test_distraction_actions_are_private(client, auth):
    _start(client, auth)
    distraction = _detect(client, auth).json()
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    assert client.post(f"{API}/distractions/{distraction['id']}/end", headers=other, json={}).status_code == 404
    assert client.post(f"{API}/distractions/{distraction['id']}/dismiss", headers=other, json={}).status_code == 404


def test_live_events_for_activity_and_settings(client, auth):
    token = auth["Authorization"].removeprefix("Bearer ")
    with client.websocket_connect(f"{API}/ws?token={token}") as ws:
        ws.receive_json()  # snapshot
        _report(client, auth, CHROME, "Netflix - Google Chrome")
        event = ws.receive_json()
        assert event["type"] == "activity.updated"
        assert event["activity"]["subject"] == "Netflix"
        assert event["activity"]["title"] == "Netflix"

        client.patch(f"{API}/settings", headers=auth, json={"screen_tracking_enabled": False})
        event = ws.receive_json()
        assert event == {"type": "settings.updated", "settings": event["settings"]}
        assert event["settings"]["screen_tracking_enabled"] is False
