from datetime import UTC, datetime, timedelta

from app.core.timeutils import now_utc
from tests.conftest import API, login_headers, register
from tests.helpers import iso, log_distraction, make_session


def test_manual_distraction_defaults_to_now(client, auth):
    response = client.post(f"{API}/distractions/manual", headers=auth, json={"reason": "Phone"})
    assert response.status_code == 201
    body = response.json()
    assert body["event_type"] == "manual"
    assert body["inactive_minutes"] is None
    assert abs(datetime.fromisoformat(body["timestamp"]) - now_utc()) < timedelta(seconds=10)


def test_inferred_distraction_stores_minutes_and_default_reason(client, auth):
    body = client.post(f"{API}/distractions/inferred", headers=auth, json={"inactive_minutes": 12}).json()
    assert body["event_type"] == "inferred"
    assert body["inactive_minutes"] == 12
    assert body["reason"] == "Inactive for 12 minutes"

    custom = client.post(
        f"{API}/distractions/inferred", headers=auth, json={"inactive_minutes": 3, "reason": "Away"}
    ).json()
    assert custom["reason"] == "Away"
    assert client.post(f"{API}/distractions/inferred", headers=auth, json={"inactive_minutes": 0}).status_code == 422


def test_distraction_session_must_be_owned_and_in_range(client, auth):
    start = now_utc() - timedelta(hours=2)
    session = make_session(client, auth, start, start + timedelta(minutes=30))

    inside = client.post(
        f"{API}/distractions/manual",
        headers=auth,
        json={"session_id": session["id"], "timestamp": iso(start + timedelta(minutes=10))},
    )
    outside = client.post(
        f"{API}/distractions/manual",
        headers=auth,
        json={"session_id": session["id"], "timestamp": iso(start + timedelta(hours=1))},
    )
    future = client.post(
        f"{API}/distractions/manual", headers=auth, json={"timestamp": iso(now_utc() + timedelta(hours=1))}
    )
    assert inside.status_code == 201
    assert outside.status_code == 400
    assert future.status_code == 400

    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    stolen = client.post(f"{API}/distractions/manual", headers=other, json={"session_id": session["id"]})
    assert stolen.status_code == 404


def test_list_distractions_pagination_and_day_filter(client):
    register(client, email="tz@example.com", timezone="America/New_York")
    headers = login_headers(client, email="tz@example.com")
    # 02:00 UTC on Jan 16 is still Jan 15 in New York (UTC-5).
    log_distraction(client, headers, datetime(2026, 1, 16, 2, 0, tzinfo=UTC), reason="late night")
    for hour in (14, 15, 16):
        log_distraction(client, headers, datetime(2026, 1, 15, hour, 0, tzinfo=UTC))
    log_distraction(client, headers, datetime(2026, 1, 16, 15, 0, tzinfo=UTC))

    day = client.get(f"{API}/distractions", headers=headers, params={"day": "2026-01-15"}).json()
    assert day["total_count"] == 4
    assert day["items"][0]["reason"] == "late night"  # newest first

    page = client.get(f"{API}/distractions", headers=headers, params={"limit": 2, "offset": 4}).json()
    assert page["total_count"] == 5
    assert len(page["items"]) == 1
    assert client.get(f"{API}/distractions", headers=headers, params={"limit": 500}).status_code == 422


def test_daily_summary_splits_manual_and_inferred(client, auth):
    when = datetime(2026, 1, 20, 10, tzinfo=UTC)
    log_distraction(client, auth, when)
    log_distraction(client, auth, when + timedelta(minutes=5))
    client.post(f"{API}/distractions/inferred", headers=auth, json={"inactive_minutes": 5, "timestamp": iso(when)})

    summary = client.get(f"{API}/distractions/summary/daily", headers=auth, params={"day": "2026-01-20"}).json()
    assert summary == {
        "day": "2026-01-20",
        "total_events": 3,
        "manual_events": 2,
        "inferred_events": 1,
        "screen_events": 0,
        "camera_events": 0,
    }

    empty = client.get(f"{API}/distractions/summary/daily", headers=auth).json()
    assert empty["total_events"] == 0
