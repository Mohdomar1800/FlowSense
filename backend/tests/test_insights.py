"""Insight rules (pure, with hand-built histories) and the /insights/recommendations endpoint."""

from datetime import UTC, date, datetime, timedelta

from app.core.timeutils import now_utc
from app.models.distraction_event import DistractionType
from app.services import insight as engine
from app.services.insight import DistractionInfo, History, SessionInfo
from tests.conftest import API
from tests.helpers import iso, log_distraction, make_session

TODAY = date(2026, 3, 28)  # a Saturday


def at(days_ago: int, hour: int, minute: int = 0) -> datetime:
    d = TODAY - timedelta(days=days_ago)
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=UTC)


def session(days_ago, hour, minutes=50, score=80, tagged=True, offsets=(), paused=0):
    return SessionInfo(at(days_ago, hour), minutes * 60, paused, score, tagged, [o * 60 for o in offsets])


def history(sessions=(), distractions=(), goal_minutes=120, splits=0):
    sessions = list(sessions)
    return History(
        today=TODAY,
        goal_seconds=goal_minutes * 60,
        sessions=sessions,
        distractions=list(distractions),
        long_pause_splits=splits,
        first_day=min((s.start.date() for s in sessions), default=None),
    )


def ids(candidates):
    if candidates is None:
        return []
    if not isinstance(candidates, list):
        candidates = [candidates]
    return [c.item.id for c in candidates]


# --- time of day ----------------------------------------------------------------------------------


def test_best_and_worst_windows():
    morning = [session(d, 9, score=92) for d in range(1, 5)]
    afternoon = [session(d, 13, score=80) for d in range(1, 4)]
    evening = [session(d, 19, score=55) for d in range(1, 5)]
    result = engine._time_of_day(history(morning + afternoon + evening))
    by_id = {c.item.id: c.item for c in result}
    assert set(by_id) == {"best_window", "worst_window"}
    assert by_id["best_window"].title == "You focus best 9 AM–12 PM"
    assert by_id["worst_window"].title == "Focus dips 6 PM–9 PM"
    assert by_id["worst_window"].kind == "improve" and by_id["worst_window"].tip


def test_time_of_day_needs_enough_sessions_and_a_real_difference():
    assert engine._time_of_day(history([session(1, 9, score=95), session(2, 19, score=40)])) == []
    flat = [session(d, 9, score=80) for d in range(1, 5)] + [session(d, 19, score=78) for d in range(1, 5)]
    assert engine._time_of_day(history(flat)) == []


# --- session length -------------------------------------------------------------------------------


def test_distractions_climbing_late_in_sessions():
    # 10 sessions of 90 min: calm for the first 45 minutes, then distractions pile up.
    sessions = [session(d, 9, minutes=90, offsets=(50, 60, 75)) for d in range(1, 11)]
    result = engine._session_length(history(sessions))
    assert result.item.id == "session_length"
    assert result.item.title == "Distractions climb after about 45 minutes"
    assert "40-minute sessions" in result.item.tip
    assert result.item.confidence == "medium"


def test_even_distractions_do_not_suggest_shorter_sessions():
    sessions = [session(d, 9, minutes=90, offsets=(10, 40, 70)) for d in range(1, 11)]
    assert engine._session_length(history(sessions)) is None


def test_session_length_needs_data():
    sessions = [session(d, 9, minutes=90, offsets=(60, 70)) for d in range(1, 4)]
    assert engine._session_length(history(sessions)) is None


# --- distractions ---------------------------------------------------------------------------------


def screen(days_ago, subject, minutes, kind=DistractionType.SCREEN):
    return DistractionInfo(at(days_ago, 10), kind, subject, minutes * 60)


def test_costliest_distraction_with_tailored_tip():
    distractions = [screen(1, "YouTube", 8), screen(2, "YouTube", 9), screen(3, "Reddit", 2)]
    item = engine._costliest_distraction(history(distractions=distractions)).item
    assert item.title == "YouTube is your biggest time sink"
    assert "17 min" in item.message and "Always flag" in item.tip

    phone = [screen(d, "Phone", 3, DistractionType.CAMERA) for d in range(1, 6)]
    assert "another room" in engine._costliest_distraction(history(distractions=phone)).item.tip


def test_minor_distractions_are_not_reported():
    assert engine._costliest_distraction(history(distractions=[screen(1, "YouTube", 2)])) is None
    manual_only = [DistractionInfo(at(1, 10), DistractionType.MANUAL, None, 0) for _ in range(10)]
    assert engine._costliest_distraction(history(distractions=manual_only)) is None


def test_phone_trend_both_directions():
    camera = DistractionType.CAMERA
    fewer = [screen(d, "Phone", 1, camera) for d in (8, 9, 10, 11, 12)] + [screen(1, "Phone", 1, camera)]
    assert ids(engine._phone_trend(history(distractions=fewer))) == ["phone_down"]
    more = [screen(d, "Phone", 1, camera) for d in (0, 1, 2, 3, 4, 5)] + [screen(9, "Phone", 1, camera)]
    assert ids(engine._phone_trend(history(distractions=more))) == ["phone_up"]


# --- trends and goals -----------------------------------------------------------------------------


def test_weekly_trend():
    up = [session(d, 9, minutes=90) for d in range(0, 6)] + [session(d, 9, minutes=60) for d in range(8, 12)]
    item = engine._weekly_trend(history(up)).item
    assert (item.id, item.title) == ("trend_up", "Focus time is up 125%")
    down = [session(d, 9, minutes=30) for d in range(0, 2)] + [session(d, 9, minutes=90) for d in range(8, 13)]
    assert ids(engine._weekly_trend(history(down))) == ["trend_down"]
    assert engine._weekly_trend(history([session(1, 9)])) is None  # no previous week


def test_goal_streak_counts_up_to_yesterday_when_today_is_unfinished():
    sessions = [session(d, 9, minutes=130) for d in range(1, 5)] + [session(0, 9, minutes=10)]
    item = engine._goal(history(sessions, goal_minutes=120)).item
    assert (item.id, item.title) == ("goal_streak", "4-day goal streak")


def test_goal_too_ambitious_suggests_a_realistic_one():
    sessions = [session(d, 9, minutes=45) for d in range(1, 8)]
    item = engine._goal(history(sessions, goal_minutes=180)).item
    assert item.id == "goal_too_high"
    assert "Set your goal to 45 minutes" in item.tip  # median day 45 min, +10%, rounded to 15


def test_no_goal_insight_when_goal_disabled():
    assert engine._goal(history([session(d, 9) for d in range(1, 8)], goal_minutes=0)) is None


# --- habits ---------------------------------------------------------------------------------------


def test_weakest_weekday():
    # Four weeks of 60 min a day, except Fridays with 10 min.
    sessions = [session(d, 9, minutes=10 if (TODAY - timedelta(days=d)).weekday() == 4 else 60) for d in range(1, 29)]
    item = engine._weakest_weekday(history(sessions)).item
    assert item.title == "Fridays are your quietest day"


def test_short_sessions_long_breaks_idle_and_tags():
    short = [session(d, 9, minutes=5) for d in range(1, 4)] + [session(d, 10, minutes=40) for d in range(1, 5)]
    assert ids(engine._short_sessions(history(short))) == ["short_sessions"]
    assert engine._long_breaks(history(splits=2)) is None
    assert ids(engine._long_breaks(history(splits=4))) == ["long_breaks"]
    idle = [DistractionInfo(at(d, 10), DistractionType.INFERRED, None, 0) for d in range(1, 6)]
    assert ids(engine._stepping_away(history(distractions=idle))) == ["stepping_away"]
    untagged = [session(d, 9, tagged=False) for d in range(1, 7)]
    assert ids(engine._untagged(history(untagged))) == ["tag_sessions"]


# --- endpoint -------------------------------------------------------------------------------------


def test_getting_started_with_too_little_data(client, auth):
    body = client.get(f"{API}/insights/recommendations", headers=auth).json()
    assert body["sessions_analyzed"] == 0 and body["lookback_days"] == 28
    assert [i["id"] for i in body["items"]] == ["getting_started"]
    assert "3 more sessions" in body["items"][0]["message"]


def test_endpoint_returns_ranked_evidence_backed_insights(client, auth):
    now = now_utc()
    for days_ago in range(1, 8):
        start = (now - timedelta(days=days_ago)).replace(hour=9, minute=0, second=0, microsecond=0)
        make_session(client, auth, start, start + timedelta(minutes=5))  # short, untagged sessions
    for days_ago in range(1, 6):
        start = (now - timedelta(days=days_ago)).replace(hour=14, minute=0, second=0, microsecond=0)
        session = make_session(client, auth, start, start + timedelta(minutes=40))
        log_distraction(client, auth, start + timedelta(minutes=10), session_id=session["id"])

    body = client.get(f"{API}/insights/recommendations", headers=auth).json()
    assert body["sessions_analyzed"] == 12
    found = [i["id"] for i in body["items"]]
    assert "short_sessions" in found and "tag_sessions" in found
    assert found.index("short_sessions") < found.index("tag_sessions")  # improvements outrank info
    for item in body["items"]:
        assert item["title"] and item["message"] and item["evidence"]
        assert item["kind"] in {"improve", "strength", "info"}


def test_old_and_running_sessions_are_ignored(client, auth):
    old = now_utc() - timedelta(days=40)
    for i in range(5):
        make_session(client, auth, old + timedelta(hours=i), old + timedelta(hours=i, minutes=30))
    client.post(f"{API}/sessions/start", headers=auth, json={"start_time": iso(now_utc() - timedelta(minutes=5))})
    body = client.get(f"{API}/insights/recommendations", headers=auth).json()
    assert body["sessions_analyzed"] == 0


def test_insights_cache_is_invalidated_by_new_sessions(client, auth, cache):
    assert client.get(f"{API}/insights/recommendations", headers=auth).json()["sessions_analyzed"] == 0
    start = now_utc() - timedelta(hours=1)
    make_session(client, auth, start, start + timedelta(minutes=30))
    assert client.get(f"{API}/insights/recommendations", headers=auth).json()["sessions_analyzed"] == 1
