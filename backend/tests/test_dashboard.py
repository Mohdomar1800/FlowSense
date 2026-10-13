"""GET /analytics/dashboard: totals, comparisons, daily/hourly buckets, heatmap, tags, distractions, screen time."""

from datetime import UTC, datetime, timedelta

from app.core.timeutils import now_utc
from tests.conftest import API, login_headers, register
from tests.helpers import iso, make_session

WEEK = {"period": "week", "reference_date": "2026-03-04"}  # Mon Mar 2 - Sun Mar 8


def at(day, hour, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def dashboard(client, headers, **params):
    response = client.get(f"{API}/analytics/dashboard", headers=headers, params=params or WEEK)
    assert response.status_code == 200, response.text
    return response.json()


def detect(client, headers, subject, start, seconds, source="screen"):
    created = client.post(
        f"{API}/distractions/detected",
        headers=headers,
        json={"source": source, "subject": subject, "timestamp": iso(start)},
    ).json()
    client.post(
        f"{API}/distractions/{created['id']}/end", headers=headers, json={"at": iso(start + timedelta(seconds=seconds))}
    )


def test_week_totals_days_tags_and_comparison(client, auth):
    client.patch(f"{API}/settings", headers=auth, json={"daily_focus_goal_minutes": 60})
    tag = client.post(f"{API}/tags", headers=auth, json={"name": "Math", "color": "#112233"}).json()
    make_session(client, auth, at(2, 9), at(2, 10, 30), tag["id"])  # Mon 90 min, goal met
    make_session(client, auth, at(4, 14), at(4, 14, 30))  # Wed 30 min, untagged
    make_session(client, auth, at(1, 9), at(1, 9, 45))  # previous week (Sun Mar 1)
    client.post(f"{API}/distractions/manual", headers=auth, json={"timestamp": iso(at(4, 14, 10))})

    body = dashboard(client, auth)
    assert (body["start_date"], body["end_date"], body["daily_goal_seconds"]) == ("2026-03-02", "2026-03-08", 3600)

    totals = body["totals"]
    assert totals["focus_seconds"] == 120 * 60
    assert totals["sessions"] == 2
    assert totals["average_session_seconds"] == 60 * 60
    assert totals["distractions"] == 1
    assert totals["average_focus_score"] is not None

    assert body["previous"] == {
        "start_date": "2026-02-23",
        "end_date": "2026-03-01",
        "focus_seconds": 45 * 60,
        "distractions": 0,
        "average_focus_score": 100.0,
    }

    days = {d["date"]: d for d in body["days"]}
    assert len(days) == 7
    assert days["2026-03-02"]["focus_seconds"] == 90 * 60 and days["2026-03-02"]["goal_met"] is True
    assert days["2026-03-04"]["focus_seconds"] == 30 * 60 and days["2026-03-04"]["goal_met"] is False
    assert days["2026-03-04"]["distractions"] == 1
    assert days["2026-03-05"] == {
        "date": "2026-03-05",
        "focus_seconds": 0,
        "sessions": 0,
        "distractions": 0,
        "average_focus_score": None,
        "goal_met": False,
    }

    assert body["tags"] == [
        {"tag_id": tag["id"], "name": "Math", "color": "#112233", "focus_seconds": 90 * 60},
        {"tag_id": None, "name": "No tag", "color": "#9aa1b8", "focus_seconds": 30 * 60},
    ]


def test_sessions_spread_across_the_hours_they_cover(client, auth):
    make_session(client, auth, at(3, 9, 30), at(3, 11, 30))  # Tue 09:30-11:30
    body = dashboard(client, auth)
    hours = {h["hour"]: h["focus_seconds"] for h in body["hours"]}
    assert (hours[9], hours[10], hours[11]) == (1800, 3600, 1800)
    assert sum(hours.values()) == 7200
    assert body["heatmap"] == [
        {"weekday": 1, "hour": 9, "focus_seconds": 1800},
        {"weekday": 1, "hour": 10, "focus_seconds": 3600},
        {"weekday": 1, "hour": 11, "focus_seconds": 1800},
    ]


def test_pauses_are_excluded_from_hourly_focus(client, auth):
    start = at(3, 9)
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(start)})
    client.post(f"{API}/sessions/pause", headers=auth, json={"at": iso(start + timedelta(minutes=30))})
    client.post(f"{API}/sessions/resume", headers=auth, json={"at": iso(start + timedelta(minutes=34))})
    client.post(f"{API}/sessions/stop", headers=auth, json={"at": iso(start + timedelta(minutes=64))})
    body = dashboard(client, auth)
    assert body["totals"]["focus_seconds"] == 60 * 60
    assert sum(h["focus_seconds"] for h in body["hours"]) == 60 * 60  # 64 min wall time, 60 focused


def test_buckets_use_the_users_timezone(client):
    register(client, email="tz@example.com", timezone="Asia/Kolkata")
    headers = login_headers(client, email="tz@example.com")
    make_session(client, headers, at(3, 20), at(3, 20, 30))  # 01:30 Wed Mar 4 in Kolkata
    body = dashboard(client, headers)
    day = next(d for d in body["days"] if d["focus_seconds"])
    assert day["date"] == "2026-03-04"
    assert body["heatmap"] == [{"weekday": 2, "hour": 1, "focus_seconds": 1800}]


def test_top_distractions_and_time_lost(client, auth):
    start = now_utc() - timedelta(hours=2)
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(start)})
    detect(client, auth, "YouTube", start + timedelta(minutes=5), 120)
    detect(client, auth, "YouTube", start + timedelta(minutes=20), 60)
    detect(client, auth, "Phone", start + timedelta(minutes=40), 300, source="camera")
    client.post(f"{API}/distractions/manual", headers=auth, json={"timestamp": iso(start + timedelta(minutes=50))})
    client.post(f"{API}/sessions/stop", headers=auth, json={})

    body = dashboard(client, auth, period="day")
    assert body["totals"]["time_lost_seconds"] == 480
    assert body["top_distractions"] == [
        {"subject": "YouTube", "source": "screen", "count": 2, "time_lost_seconds": 180},
        {"subject": "Phone", "source": "camera", "count": 1, "time_lost_seconds": 300},
        {"subject": "Logged manually", "source": "manual", "count": 1, "time_lost_seconds": 0},
    ]


def test_screen_time_by_category_and_top_activities(client, auth):
    start = now_utc() - timedelta(minutes=30)
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(start)})

    def report(app, title, minute):
        client.post(
            f"{API}/activity",
            headers=auth,
            json={"app": app, "title": title, "at": iso(start + timedelta(minutes=minute))},
        )

    report("Code.exe", "main.py - Visual Studio Code", 0)
    report("chrome.exe", "Funny cats - YouTube - Google Chrome", 15)
    report("explorer.exe", "Downloads", 20)
    report("Code.exe", "main.py - Visual Studio Code", 25)
    client.post(f"{API}/sessions/stop", headers=auth, json={"at": iso(start + timedelta(minutes=30))})

    body = dashboard(client, auth, period="day")
    assert body["screen_time"] == {"focus": 20 * 60, "neutral": 5 * 60, "distracting": 5 * 60}
    assert body["top_activities"][0] == {"subject": "Visual Studio Code", "category": "focus", "seconds": 1200}
    assert {a["subject"] for a in body["top_activities"]} == {"Visual Studio Code", "YouTube", "explorer.exe"}


def test_running_session_counts_live_and_is_not_cached(client, auth, cache):
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(now_utc() - timedelta(minutes=10))})
    body = dashboard(client, auth, period="day")
    assert 595 <= body["totals"]["focus_seconds"] <= 605
    assert body["totals"]["average_focus_score"] is None  # nothing finished yet
    assert not any(":dashboard:" in key for key in cache.store)


def test_cached_and_invalidated_by_goal_change(client, auth, cache):
    make_session(client, auth, at(2, 9), at(2, 10))
    assert dashboard(client, auth)["days"][0]["goal_met"] is False  # default goal is 2h
    assert any(":dashboard:" in key for key in cache.store)

    client.patch(f"{API}/settings", headers=auth, json={"daily_focus_goal_minutes": 30})
    assert not any(":dashboard:" in key for key in cache.store)
    assert dashboard(client, auth)["days"][0]["goal_met"] is True


def test_day_view_and_one_day_custom_range_are_cached_separately(client, auth, cache):
    # Reports build a one-day "custom" dashboard; the Day view of that date must not be served its cached copy.
    make_session(client, auth, at(3, 9), at(3, 10))
    custom = dashboard(client, auth, period="custom", start_date="2026-03-03", end_date="2026-03-03")
    day = dashboard(client, auth, period="day", reference_date="2026-03-03")
    assert (custom["period"], day["period"]) == ("custom", "day")


def test_custom_range_and_validation(client, auth):
    make_session(client, auth, at(2, 9), at(2, 10))
    body = dashboard(client, auth, period="custom", start_date="2026-03-01", end_date="2026-03-03")
    assert len(body["days"]) == 3
    assert body["previous"]["start_date"] == "2026-02-26"
    assert client.get(f"{API}/analytics/dashboard", headers=auth, params={"period": "custom"}).status_code == 400
    assert client.get(f"{API}/analytics/dashboard", headers=auth, params={"period": "year"}).status_code == 422


def test_empty_dashboard_and_privacy(client, auth):
    make_session(client, auth, at(2, 9), at(2, 10))
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    body = dashboard(client, other)
    assert body["totals"]["focus_seconds"] == 0 and body["totals"]["sessions"] == 0
    assert body["tags"] == [] and body["heatmap"] == [] and body["top_distractions"] == []
    assert body["screen_time"] == {"focus": 0, "neutral": 0, "distracting": 0}
