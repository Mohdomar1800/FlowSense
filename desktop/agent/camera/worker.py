"""Background camera loop: open the webcam only while needed, analyze ~2 frames/s, feed the PhoneMonitor.

The camera is released whenever tracking is inactive (no running session, session paused, or the
switch is off), so the camera light is only on while it's actually being used.
"""

import logging
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime

from agent.camera.phone_monitor import Notifier, PhoneMonitor, Server

logger = logging.getLogger(__name__)

# Seconds between analyzed frames. Phone use must persist ~6 s before it counts anyway, so 1 frame/s
# loses nothing in practice and keeps CPU use low.
FRAME_INTERVAL = 1.0
RETRY_UNAVAILABLE = 30.0  # seconds before retrying a camera that couldn't be opened


def camera_supported() -> bool:
    try:
        import cv2  # noqa: F401
    except ImportError:
        return False
    return True


class CameraWorker:
    def __init__(
        self,
        notifier: Notifier,
        camera_index: int = 0,
        analyzer_factory: Callable | None = None,
        capture_factory: Callable | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.notifier = notifier
        self.camera_index = camera_index
        self.analyzer_factory = analyzer_factory or _default_analyzer
        self.capture_factory = capture_factory or _open_camera
        self.clock = clock
        self._lock = threading.Lock()
        self._monitor: PhoneMonitor | None = None
        self._active = False
        self._analyzer = None
        self._capture = None
        self._retry_at = 0.0
        self._warned_unavailable = False
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="flowsense-camera", daemon=True)

    # ---------- control (called from the agent thread) ----------

    def start(self) -> None:
        self._thread.start()

    def shutdown(self) -> None:
        self._stop.set()
        self._wake.set()
        self._thread.join(timeout=5)

    def set_server(self, server: Server | None) -> None:
        with self._lock:
            if self._monitor is not None:
                self._monitor.stop(self.clock())
            self._monitor = PhoneMonitor(server, self.notifier) if server is not None else None

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self._wake.set()

    def dismissed(self, distraction_id: int) -> None:
        with self._lock:
            if self._monitor is not None:
                self._monitor.dismissed(distraction_id)

    @property
    def camera_open(self) -> bool:
        return self._capture is not None

    # ---------- loop ----------

    def _loop(self) -> None:
        while not self._stop.is_set():
            if not (self._active and self._monitor is not None):
                self._release()
                self._wake.wait(timeout=1.0)
                self._wake.clear()
                continue
            started = time.monotonic()
            try:
                self._process_one_frame()
            except Exception:
                logger.exception("camera frame failed")
                self._release()
                self._retry_at = time.monotonic() + RETRY_UNAVAILABLE
            self._wake.wait(timeout=max(0.0, FRAME_INTERVAL - (time.monotonic() - started)))
            self._wake.clear()
        self._release()

    def _process_one_frame(self) -> None:
        if self._capture is None and not self._open():
            return
        frame = self._read_latest()
        if frame is None:
            return
        observation = self._analyzer.analyze(frame)
        with self._lock:
            if self._monitor is not None and self._active:
                self._monitor.observe(self.clock(), observation)

    def _open(self) -> bool:
        if time.monotonic() < self._retry_at:
            return False
        if self._analyzer is None:
            self._analyzer = self.analyzer_factory()  # downloads/loads models once
        capture = self.capture_factory(self.camera_index)
        if capture is None:
            self._retry_at = time.monotonic() + RETRY_UNAVAILABLE
            if not self._warned_unavailable:
                self._warned_unavailable = True
                self.notifier.notify("Camera unavailable", "Another app may be using it. Phone detection is paused.")
            return False
        self._capture = capture
        self._warned_unavailable = False
        logger.info("camera opened")
        return True

    def _read_latest(self):
        # Drain the driver's buffer so we analyze what's in front of the camera now, not a stale frame.
        self._capture.grab()
        ok, frame = self._capture.read()
        if not ok:
            self._release()
            self._retry_at = time.monotonic() + RETRY_UNAVAILABLE
            return None
        return frame

    def _release(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
            logger.info("camera released")
        with self._lock:
            if self._monitor is not None:
                self._monitor.stop(self.clock())


def _open_camera(index: int):
    """Open the webcam at a modest resolution, or return None if it's unavailable."""
    import cv2

    backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY  # DirectShow opens fast on Windows
    capture = cv2.VideoCapture(index, backend)
    if not capture.isOpened():
        capture.release()
        return None
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return capture


def _default_analyzer():
    from agent.camera.models import ensure_models
    from agent.camera.vision import FrameAnalyzer

    face_model, object_model = ensure_models()
    return FrameAnalyzer(face_model, object_model)
