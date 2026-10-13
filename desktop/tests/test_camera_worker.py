"""CameraWorker lifecycle with a fake camera and a scripted analyzer (no webcam or models needed)."""

import time

from agent.camera.phone_monitor import Box, Detection, Observation
from agent.camera.worker import CameraWorker

FACE = Box(0.4, 0.2, 0.2, 0.3)
PHONE_USE = Observation(face=FACE, head_pitch=0.8, phones=(Detection(Box(0.42, 0.62, 0.1, 0.15), 0.9),))


class FakeCapture:
    def __init__(self) -> None:
        self.released = False
        self.reads = 0

    def grab(self):
        return True

    def read(self):
        self.reads += 1
        return True, object()  # the scripted analyzer ignores the frame

    def release(self):
        self.released = True


class ScriptedAnalyzer:
    def __init__(self, observation: Observation) -> None:
        self.observation = observation

    def analyze(self, frame) -> Observation:
        return self.observation


class FakeServer:
    def __init__(self) -> None:
        self.logged, self.ended = [], []

    def log_distraction(self, subject, reason, started_at, source="screen"):
        self.logged.append((subject, source))
        return len(self.logged)

    def end_distraction(self, distraction_id, at):
        self.ended.append(distraction_id)


class Notifier:
    def __init__(self) -> None:
        self.titles = []

    def notify(self, title, message):
        self.titles.append(title)


def wait_for(condition, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.05)
    return False


def make_worker(observation=PHONE_USE, capture_available=True):
    captures: list[FakeCapture] = []

    def open_capture(index):
        if not capture_available:
            return None
        captures.append(FakeCapture())
        return captures[-1]

    notifier = Notifier()
    worker = CameraWorker(
        notifier, analyzer_factory=lambda: ScriptedAnalyzer(observation), capture_factory=open_capture
    )
    return worker, captures, notifier


def test_camera_only_opens_while_active_and_is_released_after():
    worker, captures, _ = make_worker()
    server = FakeServer()
    worker.set_server(server)
    worker.start()
    try:
        time.sleep(0.6)
        assert captures == []  # inactive: camera never opened

        worker.set_active(True)
        assert wait_for(lambda: server.logged == [("Phone", "camera")]), "phone use not reported"
        assert worker.camera_open

        worker.set_active(False)
        assert wait_for(lambda: captures[0].released), "camera not released"
        assert server.ended == [1]  # open episode closed when tracking stopped
        assert not worker.camera_open
    finally:
        worker.shutdown()


def test_unavailable_camera_warns_once_and_does_not_crash():
    worker, _, notifier = make_worker(capture_available=False)
    worker.set_server(FakeServer())
    worker.start()
    try:
        worker.set_active(True)
        assert wait_for(lambda: notifier.titles == ["Camera unavailable"])
        time.sleep(1.0)
        assert notifier.titles == ["Camera unavailable"]
    finally:
        worker.shutdown()


def test_without_signed_in_user_nothing_runs():
    worker, captures, _ = make_worker()
    worker.start()
    try:
        worker.set_active(True)  # active but no server (signed out)
        time.sleep(0.8)
        assert captures == []
    finally:
        worker.shutdown()
