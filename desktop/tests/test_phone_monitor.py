"""PhoneMonitor: phone use vs. note-taking, driven by synthetic observations at 2 frames per second."""

from datetime import UTC, datetime, timedelta

import pytest

from agent.camera.phone_monitor import Box, Detection, Observation, PhoneMonitor

T0 = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
FACE = Box(0.40, 0.20, 0.20, 0.30)  # face in the upper middle of the frame
LOOKING_AT_SCREEN = 0.55
LOOKING_DOWN = 0.75

PHONE_IN_HAND = Detection(Box(0.42, 0.62, 0.10, 0.15), 0.8)  # below the face, in the user's hands
PHONE_AT_FACE = Detection(Box(0.55, 0.25, 0.08, 0.14), 0.8)  # held up next to the face
PHONE_ON_DESK_FAR = Detection(Box(0.88, 0.88, 0.08, 0.08), 0.7)  # far corner of the frame
FAINT_PHONE = Detection(Box(0.42, 0.62, 0.10, 0.15), 0.2)  # low confidence (e.g. a pen)

SCREEN = Observation(face=FACE, head_pitch=LOOKING_AT_SCREEN)
WRITING_NOTES = Observation(face=FACE, head_pitch=LOOKING_DOWN)
SCROLLING_PHONE = Observation(face=FACE, head_pitch=LOOKING_DOWN, phones=(PHONE_IN_HAND,))
PHONE_CALL_POSE = Observation(face=FACE, head_pitch=LOOKING_AT_SCREEN, phones=(PHONE_AT_FACE,))
HEAD_BOWED_OVER_PHONE = Observation(face=None, head_pitch=None, phones=(PHONE_IN_HAND,))
PHONE_LYING_AROUND = Observation(face=FACE, head_pitch=LOOKING_AT_SCREEN, phones=(PHONE_ON_DESK_FAR,))
NOTES_WITH_PEN = Observation(face=FACE, head_pitch=LOOKING_DOWN, phones=(FAINT_PHONE,))
AWAY = Observation()


class FakeServer:
    def __init__(self) -> None:
        self.logged: list[tuple[str, str, datetime]] = []
        self.ended: list[tuple[int, datetime]] = []
        self.fail = False

    def log_distraction(self, subject, reason, started_at, source="screen"):
        if self.fail:
            raise ConnectionError("down")
        self.logged.append((subject, source, started_at))
        return len(self.logged)

    def end_distraction(self, distraction_id, at):
        self.ended.append((distraction_id, at))


class FakeNotifier:
    def __init__(self) -> None:
        self.titles: list[str] = []

    def notify(self, title, message):
        self.titles.append(title)


@pytest.fixture
def setup():
    server, notifier = FakeServer(), FakeNotifier()
    return PhoneMonitor(server, notifier), server, notifier


def feed(monitor, start_s: float, seconds: float, observation: Observation, fps: int = 2) -> float:
    """Feed `seconds` of identical frames starting at `start_s`; returns the next start time."""
    for i in range(int(seconds * fps)):
        monitor.observe(T0 + timedelta(seconds=start_s + i / fps), observation)
    return start_s + seconds


def warm_up(monitor) -> float:
    """A minute of normal screen work, so the monitor learns the user's usual head angle."""
    return feed(monitor, 0, 60, SCREEN)


# --- what must NOT trigger ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "observation",
    [WRITING_NOTES, PHONE_LYING_AROUND, NOTES_WITH_PEN, AWAY, SCREEN],
    ids=["writing-notes", "phone-lying-around", "pen-low-confidence", "away-from-desk", "working"],
)
def test_no_alert(setup, observation):
    monitor, server, notifier = setup
    feed(monitor, warm_up(monitor), 120, observation)
    assert server.logged == []
    assert notifier.titles == []


def test_brief_glance_at_phone_is_ignored(setup):
    monitor, server, _ = setup
    t = warm_up(monitor)
    t = feed(monitor, t, 2, SCROLLING_PHONE)  # 2 s: checking the time
    feed(monitor, t, 30, SCREEN)
    assert server.logged == []


def test_flickering_detection_is_ignored(setup):
    monitor, server, _ = setup
    t = warm_up(monitor)
    for _ in range(20):  # detector fires on every other frame only
        t = feed(monitor, t, 0.5, SCROLLING_PHONE)
        t = feed(monitor, t, 1.0, WRITING_NOTES)
    assert server.logged == []


# --- what MUST trigger ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "observation",
    [SCROLLING_PHONE, PHONE_CALL_POSE, HEAD_BOWED_OVER_PHONE],
    ids=["scrolling-in-lap", "phone-at-face", "head-bowed-over-phone"],
)
def test_phone_use_is_detected(setup, observation):
    monitor, server, notifier = setup
    t = warm_up(monitor)
    feed(monitor, t, 10, observation)
    assert len(server.logged) == 1
    subject, source, started = server.logged[0]
    assert (subject, source) == ("Phone", "camera")
    assert started == T0 + timedelta(seconds=t)  # timed from the first frame of use, not from detection
    assert notifier.titles == ["Phone down?"]


def test_episode_ends_when_phone_is_put_away(setup):
    monitor, server, _ = setup
    t = warm_up(monitor)
    t = feed(monitor, t, 30, SCROLLING_PHONE)
    t = feed(monitor, t, 10, WRITING_NOTES)  # phone away, back to notes
    assert len(server.ended) == 1
    distraction_id, ended_at = server.ended[0]
    assert distraction_id == 1
    assert T0 + timedelta(seconds=t - 10) < ended_at <= T0 + timedelta(seconds=t)


def test_long_phone_use_is_one_episode_with_reminders(setup):
    monitor, server, notifier = setup
    feed(monitor, warm_up(monitor), 5 * 60, SCROLLING_PHONE)
    assert len(server.logged) == 1
    assert notifier.titles == ["Phone down?", "Still on your phone", "Still on your phone"]


def test_uses_learned_head_angle_not_a_fixed_one(setup):
    """With a low webcam everyone 'looks down' a bit; only a tilt beyond the user's own normal counts."""
    monitor, server, _ = setup
    camera_below_screen = Observation(face=FACE, head_pitch=0.70)
    t = feed(monitor, 0, 60, camera_below_screen)
    assert abs(monitor.baseline_pitch() - 0.70) < 1e-9
    # Phone visible below, but head at the user's normal angle: not engaging with it.
    t = feed(monitor, t, 30, Observation(face=FACE, head_pitch=0.70, phones=(PHONE_ON_DESK_FAR,)))
    assert server.logged == []
    feed(monitor, t, 10, Observation(face=FACE, head_pitch=0.86, phones=(PHONE_IN_HAND,)))
    assert len(server.logged) == 1


def test_lots_of_note_taking_does_not_hide_phone_use(setup):
    """Someone who writes notes most of the time: 'looking down' must not become their normal."""
    monitor, server, _ = setup
    t = 0.0
    for _ in range(10):  # 70% writing notes, 30% looking at the screen
        t = feed(monitor, t, 14, WRITING_NOTES)
        t = feed(monitor, t, 6, SCREEN)
    assert abs(monitor.baseline_pitch() - LOOKING_AT_SCREEN) < 1e-9
    assert server.logged == []
    feed(monitor, t, 10, SCROLLING_PHONE)
    assert len(server.logged) == 1


def test_dismissed_episode_is_not_reflagged_until_phone_is_gone(setup):
    monitor, server, _ = setup
    t = warm_up(monitor)
    t = feed(monitor, t, 10, SCROLLING_PHONE)
    monitor.dismissed(1)
    t = feed(monitor, t, 60, SCROLLING_PHONE)  # e.g. a 2FA code the user needed
    assert len(server.logged) == 1
    t = feed(monitor, t, 10, SCREEN)  # phone put away
    feed(monitor, t, 10, SCROLLING_PHONE)  # picked up again later: counts
    assert len(server.logged) == 2


def test_stop_ends_episode(setup):
    monitor, server, _ = setup
    t = feed(monitor, warm_up(monitor), 10, SCROLLING_PHONE)
    monitor.stop(T0 + timedelta(seconds=t))
    assert server.ended == [(1, T0 + timedelta(seconds=t))]


def test_server_failure_is_retried(setup):
    monitor, server, _ = setup
    t = warm_up(monitor)
    server.fail = True
    t = feed(monitor, t, 10, SCROLLING_PHONE)
    assert server.logged == []
    server.fail = False
    feed(monitor, t, 1, SCROLLING_PHONE)
    assert len(server.logged) == 1
