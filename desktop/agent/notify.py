"""Native desktop notifications (Windows balloon/toast, macOS Notification Center, Linux notify-send)."""

import logging
import threading
import time

logger = logging.getLogger(__name__)


class DesktopNotifier:
    """Shows OS notifications without blocking the caller, and never more than one per `min_interval`."""

    def __init__(self, min_interval: float = 10.0) -> None:
        self.min_interval = min_interval
        self._last = 0.0
        self._lock = threading.Lock()

    def notify(self, title: str, message: str) -> None:
        with self._lock:
            now = time.monotonic()
            if now - self._last < self.min_interval:
                logger.debug("notification suppressed (rate limit): %s", title)
                return
            self._last = now
        threading.Thread(target=self._show, args=(title, message), name="flowsense-notify", daemon=True).start()

    @staticmethod
    def _show(title: str, message: str) -> None:
        try:
            from plyer import notification

            notification.notify(title=title, message=message[:250], app_name="FlowSense", timeout=6)
        except Exception:
            logger.warning("could not show notification: %s - %s", title, message)
