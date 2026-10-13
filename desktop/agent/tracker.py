"""The desktop focus agent: screen tracking (once a second) and camera phone detection (its own thread).

It learns the session state and settings from the server's live WebSocket, so it starts and stops
by itself when the user presses Start/Pause/Stop in the app, and reacts at once to settings changes.
"""

import logging
import threading
from collections.abc import Callable
from datetime import UTC, datetime

from agent import window_source
from agent.client import ApiClient, ApiError, LiveListener
from agent.monitor import FocusMonitor, Notifier
from agent.notify import DesktopNotifier

logger = logging.getLogger(__name__)

TICK_SECONDS = 1.0


class FocusAgent:
    def __init__(
        self,
        base_url: str,
        notifier: Notifier | None = None,
        get_window: Callable = window_source.get_active_window,
        get_idle_seconds: Callable = window_source.get_idle_seconds,
        camera=None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """`camera` is a CameraWorker (or None to disable camera tracking on this machine)."""
        self.base_url = base_url
        self.notifier = notifier or DesktopNotifier()
        self.get_window = get_window
        self.get_idle_seconds = get_idle_seconds
        self.camera = camera
        self.clock = clock

        self._lock = threading.Lock()
        self._token: str | None = None
        self._api: ApiClient | None = None
        self._listener: LiveListener | None = None
        self._monitor: FocusMonitor | None = None
        self.session_status: str | None = None  # "active" | "paused" | None
        self.screen_enabled = False
        self.camera_enabled = False

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, name="flowsense-agent", daemon=True)

    # ---------- lifecycle ----------

    def start(self) -> None:
        if self.camera is not None:
            self.camera.start()
        self._thread.start()

    def stop(self) -> None:
        self.set_token(None)
        self._stop.set()
        self._thread.join(timeout=3)
        if self.camera is not None:
            self.camera.shutdown()

    def set_token(self, token: str | None) -> None:
        """Called by the UI on sign-in (token) and sign-out (None)."""
        with self._lock:
            if token == self._token:
                return
            if token and self._token and self._api is not None:
                # A renewed token for the same signed-in user: keep tracking state, just use the new token.
                self._token = token
                self._api.token = token
                old_listener = self._listener
                self._listener = LiveListener(self.base_url, token, self._on_live_message, self._on_unauthorized)
                renewed_listener = self._listener
            else:
                renewed_listener = None
        if renewed_listener is not None:
            if old_listener is not None:
                old_listener.stop()
            renewed_listener.start()
            return

        with self._lock:
            old_listener, self._listener = self._listener, None
            if self._monitor is not None:
                self._monitor.stop(self.clock())
            self._token, self._api, self._monitor = token, None, None
            self.session_status, self.screen_enabled, self.camera_enabled = None, False, False
            new_listener = None
            if token:
                self._api = ApiClient(self.base_url, token)
                self._monitor = FocusMonitor(self._api, self.notifier)
                new_listener = LiveListener(self.base_url, token, self._on_live_message, self._on_unauthorized)
                self._listener = new_listener
            if self.camera is not None:
                self.camera.set_active(False)
                self.camera.set_server(self._api)
        if old_listener is not None:
            old_listener.stop()
        if new_listener is not None:
            self._load_settings()
            new_listener.start()

    @property
    def screen_active(self) -> bool:
        return self._monitor is not None and self.screen_enabled and self.session_status == "active"

    @property
    def camera_active(self) -> bool:
        return self._api is not None and self.camera_enabled and self.session_status == "active"

    # ---------- inputs ----------

    def _load_settings(self) -> None:
        try:
            self._apply_settings(self._api.get_settings())
        except (ApiError, AttributeError) as error:
            logger.warning("could not load settings: %s", error)

    def _apply_settings(self, settings: dict) -> None:
        with self._lock:
            self.screen_enabled = bool(settings.get("screen_tracking_enabled"))
            self.camera_enabled = bool(settings.get("camera_tracking_enabled"))
            if self._monitor is not None:
                self._monitor.set_grace(int(settings.get("distraction_grace_seconds", 15)))

    def _on_live_message(self, message: dict) -> None:
        kind = message.get("type")
        if kind in ("snapshot", "session.updated"):
            session = message.get("session")
            status = session.get("status") if session else None
            self.session_status = None if status == "ended" else status
        elif kind == "session.deleted":
            self.session_status = None
        elif kind == "settings.updated":
            self._apply_settings(message.get("settings") or {})
        elif kind == "report.created":
            report = message.get("report") or {}
            label = "weekly" if report.get("report_type") == "weekly" else "daily"
            summary = (report.get("data") or {}).get("summary") or report.get("content", "")
            self.notifier.notify(f"Your {label} report is ready", summary)
        elif kind == "distraction.dismissed":
            distraction_id = message.get("distraction_id")
            with self._lock:
                if self._monitor is not None:
                    self._monitor.dismissed(distraction_id)
            if self.camera is not None:
                self.camera.dismissed(distraction_id)

    def _on_unauthorized(self) -> None:
        logger.info("token rejected; tracking paused until the next sign-in")
        self.session_status = None

    # ---------- loop ----------

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self._tick()
            except Exception:
                logger.exception("agent tick failed")

    def _tick(self) -> None:
        with self._lock:
            monitor, screen_active, camera_active = self._monitor, self.screen_active, self.camera_active
        if self.camera is not None:
            self.camera.set_active(camera_active)
        if monitor is None:
            return
        now = self.clock()
        if not screen_active:
            if monitor.engaged:
                monitor.stop(now)
            return
        monitor.tick(now, self.get_window(), self.get_idle_seconds())
