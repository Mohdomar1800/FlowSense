from datetime import UTC, datetime

from tests.conftest import API, login_headers, register
from tests.helpers import log_distraction, make_session

PARAMS = {"period": "week", "reference_date": "2026-03-04"}  # week of Mon Mar 2 - Sun Mar 8


def _seed_week(client, headers):
    coding = client.post(f"{API}/tags", headers=headers, json={"name": "coding"}).json()
    make_session(
        client, headers, datetime(2026, 3, 2, 9, tzinfo=UTC), datetime(2026, 3, 2, 10, tzinfo=UTC), coding["id"]
    )
    make_session(
        client, headers, datetime(2026, 3, 3, 9, tzinfo=UTC), datetime(2026, 3, 3, 9, 30, tzinfo=UTC), coding["id"]
    )
    make_session(client, headers, datetime(2026, 3, 4, 20, tzinfo=UTC), datetime(2026, 3, 4, 20, 30, tzinfo=UTC))
    make_session(
        client, headers, datetime(2026, 3, 10, 9, tzinfo=UTC), datetime(2026, 3, 10, 10, tzinfo=UTC)
    )  # next week
    log_distraction(client, headers, datetime(2026, 3, 2, 9, 15, tzinfo=UTC))
    log_distraction(client, headers, datetime(2026, 3, 4, 20, 10, tzinfo=UTC))
    log_distraction(client, headers, datetime(2026, 3, 4, 20, 20, tzinfo=UTC))
    return coding


def test_weekly_overview_tags_and_hours(client, auth):
    coding = _seed_week(client, auth)
    body = client.get(f"{API}/analytics/productivity", headers=auth, params=PARAMS).json()

    overview = body["overview"]
    assert overview["start_date"] == "2026-03-02"
    assert overview["end_date"] == "2026-03-08"
    assert overview["total_focus_seconds"] == 120 * 60
    assert overview["focus_sessions_count"] == 3
    assert overview["average_session_seconds"] == 40 * 60
    assert overview["total_distractions"] == 3

    assert body["focus_by_tag"] == [
        {"tag_id": coding["id"], "tag_name": "coding", "total_focus_seconds": 90 * 60},
        {"tag_id": None, "tag_name": None, "total_focus_seconds": 30 * 60},
    ]
    assert body["distractions_by_hour"] == [{"hour": 9, "distraction_count": 1}, {"hour": 20, "distraction_count": 2}]


def test_hours_are_in_user_timezone(client):
    register(client, email="tz@example.com", timezone="Asia/Kolkata")
    headers = login_headers(client, email="tz@example.com")
    log_distraction(client, headers, datetime(2026, 3, 4, 10, 0, tzinfo=UTC))  # 15:30 in Kolkata
    body = client.get(f"{API}/analytics/productivity", headers=headers, params=PARAMS).json()
    assert body["distractions_by_hour"] == [{"hour": 15, "distraction_count": 1}]


def test_empty_period(client, auth):
    body = client.get(f"{API}/analytics/productivity", headers=auth, params={"period": "month"}).json()
    assert body["overview"]["total_focus_seconds"] == 0
    assert body["overview"]["average_session_seconds"] == 0.0
    assert body["focus_by_tag"] == [] and body["distractions_by_hour"] == []
    assert client.get(f"{API}/analytics/productivity", headers=auth, params={"period": "year"}).status_code == 422


def test_results_are_cached_and_invalidated_on_writes(client, auth, cache):
    _seed_week(client, auth)
    first = client.get(f"{API}/analytics/productivity", headers=auth, params=PARAMS).json()
    assert len(cache.store) == 1

    # A cached response is returned as-is.
    assert client.get(f"{API}/analytics/productivity", headers=auth, params=PARAMS).json() == first

    log_distraction(client, auth, datetime(2026, 3, 5, 12, tzinfo=UTC))
    assert cache.store == {}
    refreshed = client.get(f"{API}/analytics/productivity", headers=auth, params=PARAMS).json()
    assert refreshed["overview"]["total_distractions"] == 4


def test_cache_is_per_user(client, auth, cache):
    _seed_week(client, auth)
    client.get(f"{API}/analytics/productivity", headers=auth, params=PARAMS)

    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    other_body = client.get(f"{API}/analytics/productivity", headers=other, params=PARAMS).json()
    assert other_body["overview"]["total_focus_seconds"] == 0

    # Another user's write leaves the first user's cache alone.
    log_distraction(client, other, datetime(2026, 3, 5, 12, tzinfo=UTC))
    assert len(cache.store) == 1
