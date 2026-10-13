"""FocusMonitor rules, driven with a fake server, fake notifier and a controlled clock."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.monitor import FocusMonitor, Verdict
from agent.window_source import Window

T0 = datetime(2026, 10, 2, 10, 0, tzinfo=UTC)
CODE = Window("Code.exe", "main.py - Visual Studio Code")
CATS = Window("chrome.exe", "Funny cats - YouTube - Google Chrome")
INSTA = Window("chrome.exe", "Instagram - Google Chrome")
SEARCH = Window("chrome.exe", "weather - Google Search - Google Chrome")

VERDICTS = {
    CODE: Verdict("focus", "Visual Studio Code", "work app"),
    CATS: Verdict("distracting", "YouTube", "YouTube video unrelated to your session"),
    INSTA: Verdict("distracting", "Instagram", "Instagram is usually a distraction"),
    SEARCH: Verdict("neutral", "Google Search", "not in any list"),
    Window("", ""): Verdict("neutral", "Unknown app", "not in any list"),
}


class FakeServer:
    def __init__(self) -> None:
        self.reports: list[Window] = []
        self.distractions: list[tuple[str, datetime]] = []
        self.ended: list[tuple[int, datetime]] = []
        self.inactivity: list[tuple[int, datetime]] = []
        self.fail = False

    def report_activity(self, window, at):
        if self.fail:
            raise ConnectionError("server down")
        self.reports.append(window)
        return VERDICTS[window]

    def log_distraction(self, subject, reason, started_at):
        if self.fail:
            raise ConnectionError("server down")
        self.distractions.append((subject, started_at))
        return len(self.distractions)

    def end_distraction(self, distraction_id, at):
        self.ended.append((distraction_id, at))

    def log_inactivity(self, minutes, started_at):
        self.inactivity.append((minutes, started_at))


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def notify(self, title, message):
        self.messages.append(title)


@pytest.fixture
def setup():
    server, notifier = FakeServer(), FakeNotifier()
    return FocusMonitor(server, notifier, grace_seconds=15), server, notifier


def run(monitor, start_second, end_second, window, idle=0.0):
    for second in range(start_second, end_second):
        monitor.tick(T0 + timedelta(seconds=second), window, idle)


def test_reports_only_on_window_change(setup):
    monitor, server, _ = setup
    run(monitor, 0, 10, CODE)
    run(monitor, 10, 20, SEARCH)
    assert server.reports == [CODE, SEARCH]


def test_quick_glance_within_grace_is_not_a_distraction(setup):
    monitor, server, notifier = setup
    run(monitor, 0, 5, CODE)
    run(monitor, 5, 15, CATS)  # 10 s < 15 s grace
    run(monitor, 15, 30, CODE)
    assert server.distractions == []
    assert notifier.messages == []


def test_distraction_logged_after_grace_with_original_start_time(setup):
    monitor, server, notifier = setup
    run(monitor, 0, 5, CODE)
    run(monitor, 5, 25, CATS)
    assert server.distractions == [("YouTube", T0 + timedelta(seconds=5))]  # when it began, not when it was logged
    assert notifier.messages == ["Back to focus?"]

    run(monitor, 25, 30, CODE)
    assert server.ended == [(1, T0 + timedelta(seconds=25))]
    assert notifier.messages == ["Back to focus?", "Welcome back"]


def test_hopping_between_distractions_is_one_episode(setup):
    monitor, server, _ = setup
    run(monitor, 0, 10, CATS)
    run(monitor, 10, 20, INSTA)  # clock keeps running from second 0
    # Named after what's on screen when it's logged; timed from when the drift began.
    assert server.distractions == [("Instagram", T0)]
    run(monitor, 20, 40, INSTA)
    assert len(server.distractions) == 1


def test_neutral_window_ends_the_episode(setup):
    monitor, server, _ = setup
    run(monitor, 0, 20, CATS)
    run(monitor, 20, 21, SEARCH)
    assert server.ended == [(1, T0 + timedelta(seconds=20))]


def test_reminders_every_two_minutes(setup):
    monitor, _, notifier = setup
    run(monitor, 0, 20 + 4 * 60, CATS)
    assert notifier.messages == ["Back to focus?", "Still distracted", "Still distracted"]


def test_stop_closes_open_episode_and_resets(setup):
    monitor, server, _ = setup
    run(monitor, 0, 20, CATS)
    monitor.stop(T0 + timedelta(seconds=30))
    assert server.ended == [(1, T0 + timedelta(seconds=30))]
    assert not monitor.engaged
    # After a reset the same window is reported again when tracking resumes.
    run(monitor, 40, 41, CATS)
    assert server.reports == [CATS, CATS]


def test_server_errors_are_retried_without_crashing(setup):
    monitor, server, _ = setup
    server.fail = True
    run(monitor, 0, 3, CATS)
    assert server.reports == []
    server.fail = False
    run(monitor, 3, 4, CATS)
    assert server.reports == []  # waits 5 s before retrying
    run(monitor, 5, 6, CATS)
    assert server.reports == [CATS]


def test_failed_distraction_log_is_retried_next_tick(setup):
    monitor, server, notifier = setup
    run(monitor, 0, 15, CATS)
    server.fail = True
    run(monitor, 15, 16, CATS)
    assert server.distractions == [] and notifier.messages == []
    server.fail = False
    run(monitor, 16, 17, CATS)
    assert server.distractions == [("YouTube", T0)]


def test_grace_can_change(setup):
    monitor, server, _ = setup
    monitor.set_grace(0)
    run(monitor, 0, 1, CATS)
    assert len(server.distractions) == 1


def test_inactivity_logged_once_but_not_on_focus_windows(setup):
    monitor, server, notifier = setup
    run(monitor, 0, 5, SEARCH, idle=6 * 60)
    assert server.inactivity == [(6, T0 - timedelta(seconds=360))]
    run(monitor, 5, 10, SEARCH, idle=7 * 60)
    assert len(server.inactivity) == 1  # once per idle stretch
    assert "Still there?" in notifier.messages

    run(monitor, 10, 11, SEARCH, idle=0)  # user is back
    run(monitor, 11, 12, CODE, idle=10 * 60)  # reading a lecture in a focus app: fine
    assert len(server.inactivity) == 1


def test_dismissed_distraction_is_accepted_until_window_changes(setup):
    monitor, server, notifier = setup
    run(monitor, 0, 20, CATS)
    monitor.dismissed(1)
    run(monitor, 20, 20 + 5 * 60, CATS)  # stays on the same video for 5 more minutes
    assert len(server.distractions) == 1
    assert notifier.messages == ["Back to focus?"]  # no reminders, no "welcome back"
    assert server.ended == []  # the dismissed distraction no longer exists on the server

    run(monitor, 320, 321, CODE)
    run(monitor, 321, 340, CATS)  # coming back later counts again
    assert len(server.distractions) == 2


def test_dismissing_an_unrelated_id_changes_nothing(setup):
    monitor, server, _ = setup
    run(monitor, 0, 20, CATS)
    monitor.dismissed(999)
    assert monitor.episode_id == 1


def test_agent_announces_new_reports():
    from agent.tracker import FocusAgent

    notifier = FakeNotifier()
    agent = FocusAgent("http://127.0.0.1:1", notifier=notifier)
    agent._on_live_message(
        {"type": "report.created", "report": {"report_type": "weekly", "data": {"summary": "5h focused."}}}
    )
    assert notifier.messages == ["Your weekly report is ready"]


def test_token_renewal_keeps_tracking_state():
    """The UI renews its token every few hours; that must not end an open distraction or forget the window."""
    from agent.tracker import FocusAgent

    agent = FocusAgent("http://127.0.0.1:1", notifier=FakeNotifier())  # nothing listens there: fine for this test
    try:
        agent.set_token("first-token")
        monitor, api = agent._monitor, agent._api
        monitor.episode_id = 7  # pretend a distraction is in progress
        agent.set_token("renewed-token")
        assert agent._monitor is monitor and agent._api is api
        assert api.token == "renewed-token"
        assert monitor.episode_id == 7

        agent.set_token(None)  # signing out does reset
        assert agent._monitor is None and agent._api is None
    finally:
        agent.set_token(None)


def test_missing_window_counts_as_neutral(setup):
    monitor, server, _ = setup
    run(monitor, 0, 2, None)
    assert server.reports == [Window("", "")]
