"""Report generation (content, highlights, next goal, idempotency, timezones) and the reports API."""

from datetime import UTC, date, datetime

from app.models import ReportLog, User
from app.services import report as service
from app.services.report import generate_due_reports_for_user
from tests.conftest import API, login_headers, register
from tests.helpers import iso, log_distraction, make_session

# Wednesday 2026-03-11, 10:00 UTC: "yesterday" is Tue Mar 10, "last week" is Mon Mar 2 - Sun Mar 8.
NOW = datetime(2026, 3, 11, 10, 0, tzinfo=UTC)


def at(day, hour, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=UTC)


def _user(db, email="user@example.com") -> User:
    user = db.query(User).filter_by(email=email).one()
    user.created_at = datetime(2026, 1, 1, tzinfo=UTC)
    db.commit()
    return user


def _reports(db):
    return {r.report_type: r for r in db.query(ReportLog).all()}


def test_daily_and_weekly_reports_with_full_recap(client, db, auth):
    client.patch(f"{API}/settings", headers=auth, json={"daily_focus_goal_minutes": 60})
    tag = client.post(f"{API}/tags", headers=auth, json={"name": "Math"}).json()
    client.post(
        f"{API}/sessions/start",
        headers=auth,
        json={"start_time": iso(at(10, 9)), "intent": "Problem set 3", "tag_id": tag["id"]},
    )
    client.post(f"{API}/sessions/stop", headers=auth, json={"at": iso(at(10, 10, 30))})
    make_session(client, auth, at(4, 9), at(4, 9, 20))  # last week

    created = generate_due_reports_for_user(db, _user(db), at=NOW)
    assert [r.report_type for r in created] == ["daily", "weekly"]
    reports = _reports(db)

    daily = reports["daily"]
    assert (daily.period_start, daily.period_end) == (date(2026, 3, 10), date(2026, 3, 10))
    assert daily.content == "Tuesday, Mar 10: 1h 30m focused across 1 session, focus score 100, 0 distractions."
    data = daily.data
    assert data["title"] == "Tuesday, Mar 10"
    assert data["totals"]["focus_seconds"] == 5400
    assert data["days_goal_met"] == 1
    assert data["best_session"]["label"] == "Problem set 3"
    assert data["tags"] == [{"name": "Math", "color": "#6366f1", "focus_seconds": 5400}]
    assert "You hit your 1h 00m daily goal." in data["highlights"]
    assert "No distractions at all. Excellent focus." in data["highlights"]
    assert data["next_goal"].startswith("Beat this day's 1h 30m by 10% tomorrow")

    weekly = reports["weekly"]
    assert (weekly.period_start, weekly.period_end) == (date(2026, 3, 2), date(2026, 3, 8))
    assert weekly.data["title"] == "Week of Mar 2 – Mar 8"
    assert weekly.data["totals"]["focus_seconds"] == 1200
    assert len(weekly.data["days"]) == 7
    assert weekly.data["next_goal"] == "Meet your daily goal on at least 1 days next week."


def test_next_goal_targets_the_costliest_distraction(client, db, auth):
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(at(10, 9))})
    detected = client.post(
        f"{API}/distractions/detected",
        headers=auth,
        json={"source": "camera", "subject": "Phone", "timestamp": iso(at(10, 9, 10))},
    ).json()
    client.post(f"{API}/distractions/{detected['id']}/end", headers=auth, json={"at": iso(at(10, 9, 22))})
    client.post(f"{API}/sessions/stop", headers=auth, json={"at": iso(at(10, 10))})

    generate_due_reports_for_user(db, _user(db), at=NOW)
    data = _reports(db)["daily"].data
    assert data["top_distraction"] == {"subject": "Phone", "count": 1, "time_lost_seconds": 720}
    assert data["next_goal"] == "Keep your phone out of reach during sessions tomorrow. It cost you 12m."


def test_unmet_goal_suggests_the_remaining_time(client, db, auth):
    client.patch(f"{API}/settings", headers=auth, json={"daily_focus_goal_minutes": 120})
    make_session(client, auth, at(10, 9), at(10, 9, 45))
    generate_due_reports_for_user(db, _user(db), at=NOW)
    assert _reports(db)["daily"].data["next_goal"] == "Reach your 2h 00m goal tomorrow: 1h 15m more than today."


def test_empty_periods_get_no_report(client, db, auth):
    assert generate_due_reports_for_user(db, _user(db), at=NOW) == []
    log_distraction(client, auth, at(10, 15))  # any activity is enough
    assert [r.report_type for r in generate_due_reports_for_user(db, _user(db), at=NOW)] == ["daily"]


def test_generation_is_idempotent(client, db, auth):
    make_session(client, auth, at(10, 9), at(10, 10))
    make_session(client, auth, at(4, 9), at(4, 10))
    user = _user(db)
    assert len(generate_due_reports_for_user(db, user, at=NOW)) == 2
    assert generate_due_reports_for_user(db, user, at=NOW) == []
    assert db.query(ReportLog).count() == 2


def test_no_reports_for_periods_before_signup(client, db, auth):
    make_session(client, auth, at(10, 9), at(10, 10))
    user = db.query(User).one()
    user.created_at = datetime(2026, 3, 11, 8, tzinfo=UTC)  # signed up this morning
    db.commit()
    assert generate_due_reports_for_user(db, user, at=NOW) == []


def test_yesterday_follows_user_timezone(client, db):
    # 20:00 UTC on Mar 11 is already 05:00 on Mar 12 in Tokyo (UTC+9), so "yesterday" there is Mar 11.
    register(client, email="tokyo@example.com", timezone="Asia/Tokyo")
    headers = login_headers(client, email="tokyo@example.com")
    make_session(client, headers, at(11, 1), at(11, 2))  # 10:00-11:00 on Mar 11 in Tokyo
    user = _user(db, "tokyo@example.com")
    generate_due_reports_for_user(db, user, at=datetime(2026, 3, 11, 20, 0, tzinfo=UTC))
    daily = db.query(ReportLog).filter_by(report_type="daily").one()
    assert daily.period_start == date(2026, 3, 11)


def test_scheduler_publishes_report_ready_events(client, db, auth, monkeypatch):
    make_session(client, auth, at(10, 9), at(10, 10))
    user = _user(db)
    published = []
    monkeypatch.setattr(
        service, "publish_user_event", lambda uid, kind, payload: published.append((uid, kind, payload))
    )
    monkeypatch.setattr(service, "SessionLocal", lambda: _NoCloseSession(db))
    assert service.generate_due_reports(at=NOW) == 1
    assert [(uid, kind) for uid, kind, _ in published] == [(user.id, "report.created")]
    assert published[0][2]["report"]["data"]["title"] == "Tuesday, Mar 10"


class _NoCloseSession:
    """Lets generate_due_reports use the test transaction's session inside its `with` block."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *exc):
        return False


# --- API ------------------------------------------------------------------------------------------


def test_list_get_and_filter_reports(client, db, auth):
    for day in (2, 10, 17, 19):
        make_session(client, auth, at(day, 9), at(day, 10))
    user = _user(db)
    generate_due_reports_for_user(db, user, at=NOW)  # daily Mar 10, weekly Mar 2-8
    generate_due_reports_for_user(db, user, at=datetime(2026, 3, 20, 10, tzinfo=UTC))  # daily Mar 19, weekly Mar 9-15
    db.commit()

    all_reports = client.get(f"{API}/reports", headers=auth).json()
    assert all_reports["total_count"] == 4
    assert all_reports["items"][0]["period_start"] == "2026-03-19"
    assert all_reports["items"][0]["data"]["title"] == "Thursday, Mar 19"

    weekly = client.get(f"{API}/reports", headers=auth, params={"report_type": "weekly"}).json()
    assert [r["period_start"] for r in weekly["items"]] == ["2026-03-09", "2026-03-02"]

    ranged = client.get(f"{API}/reports", headers=auth, params={"start_date": "2026-03-10", "end_date": "2026-03-10"})
    assert {(r["report_type"], r["period_start"]) for r in ranged.json()["items"]} == {
        ("daily", "2026-03-10"),
        ("weekly", "2026-03-09"),
    }

    one = all_reports["items"][1]
    assert client.get(f"{API}/reports/{one['id']}", headers=auth).json() == one
    assert client.get(f"{API}/reports/999999", headers=auth).status_code == 404

    bad = client.get(f"{API}/reports", headers=auth, params={"start_date": "2026-03-10", "end_date": "2026-03-01"})
    assert bad.status_code == 400
    assert client.get(f"{API}/reports", headers=auth, params={"report_type": "yearly"}).status_code == 422


def test_markdown_export(client, db, auth):
    client.post(
        f"{API}/sessions/start",
        headers=auth,
        json={"start_time": iso(at(10, 9)), "intent": "Read *chapter* #4 | notes"},
    )
    client.post(f"{API}/sessions/stop", headers=auth, json={"at": iso(at(10, 10))})
    generate_due_reports_for_user(db, _user(db), at=NOW)
    db.commit()
    report = client.get(f"{API}/reports", headers=auth).json()["items"][0]

    response = client.get(f"{API}/reports/{report['id']}/export", headers=auth)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert response.headers["content-disposition"] == 'attachment; filename="flowsense-daily-report-2026-03-10.md"'
    text = response.text
    assert text.startswith("# Daily report: Tuesday, Mar 10")
    assert "| Focus time | 1h 00m |" in text
    assert "## Goal for tomorrow" in text
    assert "Read \\*chapter\\* \\#4 \\| notes" in text  # user text can't break the Markdown structure


def test_reports_are_private(client, db, auth):
    make_session(client, auth, at(10, 9), at(10, 10))
    generate_due_reports_for_user(db, _user(db), at=NOW)
    db.commit()
    report_id = client.get(f"{API}/reports", headers=auth).json()["items"][0]["id"]
    register(client, email="other@example.com")
    other = login_headers(client, email="other@example.com")
    assert client.get(f"{API}/reports", headers=other).json()["total_count"] == 0
    assert client.get(f"{API}/reports/{report_id}", headers=other).status_code == 404
    assert client.get(f"{API}/reports/{report_id}/export", headers=other).status_code == 404


def test_legacy_reports_without_data_still_work(client, db, auth):
    user = _user(db)
    db.add(
        ReportLog(
            user_id=user.id,
            report_type="daily",
            period_start=date(2026, 1, 5),
            period_end=date(2026, 1, 5),
            content="Old style report",
        )
    )
    db.commit()
    item = client.get(f"{API}/reports", headers=auth).json()["items"][0]
    assert item["data"] is None and item["content"] == "Old style report"
    assert "Old style report" in client.get(f"{API}/reports/{item['id']}/export", headers=auth).text
