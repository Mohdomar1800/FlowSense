from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.timeutils import now_utc
from app.models import FocusSession, SessionEvent, User
from tests.conftest import API, login_headers, register
from tests.helpers import iso, log_distraction, make_session


def _start(client, auth, at, **body):
    response = client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(at), **body})
    assert response.status_code == 201, response.text
    return response.json()


def _act(client, auth, action, at):
    return client.post(f"{API}/sessions/{action}", headers=auth, json={"at": iso(at)})


# --- start / stop ---------------------------------------------------------------------------------


def test_start_and_stop_computes_duration(client, auth):
    start = now_utc() - timedelta(minutes=50)
    session = make_session(client, auth, start, start + timedelta(minutes=45))
    assert session["status"] == "ended"
    assert session["duration_seconds"] == 45 * 60
    assert session["focus_score"] == 100
    assert client.get(f"{API}/sessions/active", headers=auth).json() is None


def test_start_with_defaults_and_intent(client, auth):
    response = client.post(f"{API}/sessions/start", headers=auth, json={"intent": "  Linear algebra lecture 5  "})
    session = response.json()
    assert response.status_code == 201
    assert session["status"] == "active"
    assert session["intent"] == "Linear algebra lecture 5"
    assert abs(datetime.fromisoformat(session["start_time"]) - now_utc()) < timedelta(seconds=10)
    # Pause/stop bodies are optional and default to now.
    assert client.post(f"{API}/sessions/pause", headers=auth).json()["status"] == "paused"
    assert client.post(f"{API}/sessions/stop", headers=auth).json()["status"] == "ended"


def test_only_one_open_session(client, auth):
    assert client.post(f"{API}/sessions/start", headers=auth, json={}).status_code == 201
    assert client.post(f"{API}/sessions/start", headers=auth, json={}).status_code == 409
    client.post(f"{API}/sessions/pause", headers=auth)
    # A paused session is still open.
    assert client.post(f"{API}/sessions/start", headers=auth, json={}).status_code == 409


def test_database_enforces_one_open_session(db, client, auth):
    """Even if the service check is bypassed (e.g. simultaneous requests), Postgres refuses a second open session."""
    client.post(f"{API}/sessions/start", headers=auth, json={})
    user = db.query(User).one()
    db.add(FocusSession(user_id=user.id, start_time=now_utc()))
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_database_enforces_status_consistency(db, auth):
    user = db.query(User).one()
    db.add(FocusSession(user_id=user.id, start_time=now_utc(), end_time=now_utc()))  # "active" but has an end
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_stop_validation(client, auth):
    assert client.post(f"{API}/sessions/stop", headers=auth, json={}).status_code == 404
    start = now_utc() - timedelta(minutes=10)
    _start(client, auth, start)
    assert _act(client, auth, "stop", start - timedelta(seconds=1)).status_code == 400
    assert _act(client, auth, "stop", now_utc() + timedelta(hours=1)).status_code == 400


def test_start_in_future_rejected(client, auth):
    future = now_utc() + timedelta(hours=1)
    assert client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(future)}).status_code == 400


def test_naive_datetimes_are_treated_as_utc(client, auth):
    naive = (now_utc() - timedelta(minutes=5)).replace(tzinfo=None, microsecond=0)
    session = client.post(f"{API}/sessions/start", headers=auth, json={"start_time": naive.isoformat()}).json()
    assert datetime.fromisoformat(session["start_time"]) == naive.replace(tzinfo=UTC)


# --- pause / resume -------------------------------------------------------------------------------


def test_pause_and_resume_excludes_pause_from_focus(client, auth):
    start = now_utc() - timedelta(minutes=60)
    _start(client, auth, start)

    paused = _act(client, auth, "pause", start + timedelta(minutes=20)).json()
    assert paused["status"] == "paused"
    assert paused["duration_seconds"] == 20 * 60  # frozen while paused

    resumed = _act(client, auth, "resume", start + timedelta(minutes=23)).json()
    assert resumed["split"] is False
    assert resumed["session"]["status"] == "active"
    assert resumed["session"]["paused_seconds"] == 3 * 60

    stopped = _act(client, auth, "stop", start + timedelta(minutes=50)).json()
    assert stopped["duration_seconds"] == 47 * 60
    assert stopped["paused_seconds"] == 3 * 60


def test_stop_while_paused_counts_remaining_pause(client, auth):
    start = now_utc() - timedelta(minutes=60)
    _start(client, auth, start)
    _act(client, auth, "pause", start + timedelta(minutes=30))
    stopped = _act(client, auth, "stop", start + timedelta(minutes=40)).json()
    assert stopped["duration_seconds"] == 30 * 60
    assert stopped["paused_seconds"] == 10 * 60
    assert stopped["paused_at"] is None


def test_long_pause_splits_session(client, auth):
    start = now_utc() - timedelta(minutes=90)
    tag = client.post(f"{API}/tags", headers=auth, json={"name": "work"}).json()
    original = _start(client, auth, start, tag_id=tag["id"], intent="Thesis")
    _act(client, auth, "pause", start + timedelta(minutes=20))
    response = _act(client, auth, "resume", start + timedelta(minutes=40))  # 20 min > default 5 min threshold
    body = response.json()

    assert response.status_code == 200
    assert body["split"] is True
    previous = body["previous_session"]
    assert previous["id"] == original["id"]
    assert previous["status"] == "ended"
    assert previous["duration_seconds"] == 20 * 60
    assert datetime.fromisoformat(previous["end_time"]) == start + timedelta(minutes=20)  # ends where the pause began

    new = body["session"]
    assert new["status"] == "active"
    assert new["tag_id"] == tag["id"] and new["intent"] == "Thesis"
    assert datetime.fromisoformat(new["start_time"]) == start + timedelta(minutes=40)
    assert client.get(f"{API}/sessions/active", headers=auth).json()["id"] == new["id"]


def test_pause_resume_state_errors(client, auth):
    assert client.post(f"{API}/sessions/pause", headers=auth).status_code == 404
    assert client.post(f"{API}/sessions/resume", headers=auth).status_code == 404

    start = now_utc() - timedelta(minutes=30)
    _start(client, auth, start)
    assert client.post(f"{API}/sessions/resume", headers=auth).status_code == 409  # not paused
    assert _act(client, auth, "pause", start - timedelta(minutes=1)).status_code == 400  # before start

    _act(client, auth, "pause", start + timedelta(minutes=10))
    assert client.post(f"{API}/sessions/pause", headers=auth).status_code == 409  # already paused
    assert _act(client, auth, "resume", start + timedelta(minutes=9)).status_code == 400  # before pause


def test_events_must_be_in_order(client, auth):
    start = now_utc() - timedelta(minutes=30)
    _start(client, auth, start)
    _act(client, auth, "pause", start + timedelta(minutes=10))
    _act(client, auth, "resume", start + timedelta(minutes=12))
    # Pausing again "in the past", before the resume, would corrupt the timeline.
    assert _act(client, auth, "pause", start + timedelta(minutes=11)).status_code == 400
    assert _act(client, auth, "stop", start + timedelta(minutes=11)).status_code == 400


def test_pause_threshold_comes_from_settings(client, auth):
    client.patch(f"{API}/settings", headers=auth, json={"pause_threshold_seconds": 3600})
    start = now_utc() - timedelta(minutes=90)
    _start(client, auth, start)
    _act(client, auth, "pause", start + timedelta(minutes=10))
    assert _act(client, auth, "resume", start + timedelta(minutes=40)).json()["split"] is False


# --- live values ----------------------------------------------------------------------------------


def test_open_session_reports_live_duration(client, auth):
    _start(client, auth, now_utc() - timedelta(minutes=30))
    active = client.get(f"{API}/sessions/active", headers=auth).json()
    assert 30 * 60 - 5 <= active["duration_seconds"] <= 30 * 60 + 5

    listed = client.get(f"{API}/sessions", headers=auth).json()
    assert 30 * 60 - 5 <= listed["total_focus_seconds"] <= 30 * 60 + 5


# --- timeline, edit, delete -----------------------------------------------------------------------


def test_session_detail_timeline(client, auth):
    start = now_utc() - timedelta(minutes=60)
    session = _start(client, auth, start)
    _act(client, auth, "pause", start + timedelta(minutes=10))
    _act(client, auth, "resume", start + timedelta(minutes=12))
    log_distraction(client, auth, start + timedelta(minutes=15), reason="Phone")
    _act(client, auth, "stop", start + timedelta(minutes=30))

    detail = client.get(f"{API}/sessions/{session['id']}", headers=auth).json()
    assert [item["kind"] for item in detail["timeline"]] == ["started", "paused", "resumed", "distraction", "stopped"]
    assert detail["timeline"][2]["details"] == {"pause_seconds": 120}
    assert detail["timeline"][3]["details"]["reason"] == "Phone"
    assert detail["distraction_count"] == 1


def test_split_is_visible_in_timelines(client, auth, db):
    start = now_utc() - timedelta(minutes=90)
    original = _start(client, auth, start)
    _act(client, auth, "pause", start + timedelta(minutes=20))
    new = _act(client, auth, "resume", start + timedelta(minutes=40)).json()["session"]

    old_timeline = client.get(f"{API}/sessions/{original['id']}", headers=auth).json()["timeline"]
    assert old_timeline[-1]["kind"] == "stopped"
    assert old_timeline[-1]["details"]["reason"] == "long_pause"
    new_timeline = client.get(f"{API}/sessions/{new['id']}", headers=auth).json()["timeline"]
    assert new_timeline == [
        {"kind": "started", "timestamp": new_timeline[0]["timestamp"], "details": {"split_from": original["id"]}}
    ]


def test_update_session_tag_and_intent(client, auth):
    tag = client.post(f"{API}/tags", headers=auth, json={"name": "math"}).json()
    session = client.post(f"{API}/sessions/start", headers=auth, json={"intent": "old"}).json()

    updated = client.patch(f"{API}/sessions/{session['id']}", headers=auth, json={"tag_id": tag["id"]}).json()
    assert updated["tag_id"] == tag["id"] and updated["intent"] == "old"  # unset fields untouched

    cleared = client.patch(
        f"{API}/sessions/{session['id']}", headers=auth, json={"tag_id": None, "intent": "new"}
    ).json()
    assert cleared["tag_id"] is None and cleared["intent"] == "new"
    assert client.patch(f"{API}/sessions/{session['id']}", headers=auth, json={"tag_id": 999999}).status_code == 404


def test_delete_session_removes_its_distractions_and_events(client, auth, db):
    start = now_utc() - timedelta(minutes=60)
    session = make_session(client, auth, start, start + timedelta(minutes=30))
    log_distraction(client, auth, start + timedelta(minutes=5), session_id=session["id"])

    assert client.delete(f"{API}/sessions/{session['id']}", headers=auth).status_code == 204
    assert client.get(f"{API}/sessions/{session['id']}", headers=auth).status_code == 404
    assert client.get(f"{API}/distractions", headers=auth).json()["total_count"] == 0
    assert db.query(SessionEvent).count() == 0

    # Deleting the open session frees the slot for a new one.
    client.post(f"{API}/sessions/start", headers=auth, json={})
    active = client.get(f"{API}/sessions/active", headers=auth).json()
    client.delete(f"{API}/sessions/{active['id']}", headers=auth)
    assert client.post(f"{API}/sessions/start", headers=auth, json={}).status_code == 201


def test_sessions_are_private(client, auth):
    start = now_utc() - timedelta(minutes=30)
    session = make_session(client, auth, start, start + timedelta(minutes=10))
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    assert client.get(f"{API}/sessions", headers=other).json()["sessions"] == []
    assert client.get(f"{API}/sessions/{session['id']}", headers=other).status_code == 404
    assert client.patch(f"{API}/sessions/{session['id']}", headers=other, json={"intent": "x"}).status_code == 404
    assert client.delete(f"{API}/sessions/{session['id']}", headers=other).status_code == 404


# --- listing --------------------------------------------------------------------------------------


def test_list_sessions_uses_user_timezone(client):
    # 23:30 UTC on Mar 9 is already Mar 10 in Kolkata (UTC+5:30).
    register(client, email="tz@example.com", timezone="Asia/Kolkata")
    headers = login_headers(client, email="tz@example.com")
    late_utc = datetime(2026, 3, 9, 23, 30, tzinfo=UTC)
    make_session(client, headers, late_utc, late_utc + timedelta(minutes=20))

    mar_10 = client.get(f"{API}/sessions", headers=headers, params={"period": "day", "reference_date": "2026-03-10"})
    mar_9 = client.get(f"{API}/sessions", headers=headers, params={"period": "day", "reference_date": "2026-03-09"})
    assert len(mar_10.json()["sessions"]) == 1
    assert mar_10.json()["total_focus_seconds"] == 20 * 60
    assert mar_9.json()["sessions"] == []


def test_list_sessions_periods_and_custom_range(client, auth):
    make_session(client, auth, datetime(2026, 2, 2, 9, tzinfo=UTC), datetime(2026, 2, 2, 10, tzinfo=UTC))  # Monday
    make_session(client, auth, datetime(2026, 2, 8, 9, tzinfo=UTC), datetime(2026, 2, 8, 9, 30, tzinfo=UTC))  # Sunday
    make_session(client, auth, datetime(2026, 2, 9, 9, tzinfo=UTC), datetime(2026, 2, 9, 9, 15, tzinfo=UTC))  # next wk

    def get(**params):
        return client.get(f"{API}/sessions", headers=auth, params=params)

    assert get(period="week", reference_date="2026-02-05").json()["total_focus_seconds"] == 90 * 60
    assert len(get(period="month", reference_date="2026-02-20").json()["sessions"]) == 3
    custom = get(period="custom", start_date="2026-02-08", end_date="2026-02-09").json()
    assert len(custom["sessions"]) == 2
    assert custom["sessions"][0]["start_time"].startswith("2026-02-09")  # newest first

    assert get(period="custom", start_date="2026-02-08").status_code == 400
    assert get(period="custom", start_date="2026-02-09", end_date="2026-02-08").status_code == 400
    assert get(period="year").status_code == 422
