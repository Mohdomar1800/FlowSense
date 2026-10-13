"""HTTP and WebSocket access to the FlowSense server for the desktop agent (standard library + websockets)."""

import json
import logging
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime
from urllib.parse import quote

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

from agent.monitor import Verdict
from agent.window_source import Window

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status


class ApiClient:
    """Implements monitor.Server against the REST API."""

    def __init__(self, base_url: str, token: str, timeout: float = 4.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None) -> dict | None:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"{self.base_url}/api/v1{path}",
            data=data,
            method=method,
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            try:
                message = json.loads(error.read())["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = error.reason
            raise ApiError(error.code, str(message)) from error
        except (urllib.error.URLError, OSError) as error:
            raise ApiError(0, str(error)) from error

    def get_settings(self) -> dict:
        return self._request("GET", "/settings")

    def report_activity(self, window: Window, at: datetime) -> Verdict:
        result = self._request("POST", "/activity", {"app": window.app, "title": window.title, "at": at.isoformat()})
        return Verdict(category=result["category"], subject=result["subject"], reason=result["reason"])

    def log_distraction(self, subject: str, reason: str, started_at: datetime, source: str = "screen") -> int:
        body = {
            "source": source,
            "subject": subject[:120],
            "reason": reason[:255] or None,
            "timestamp": started_at.isoformat(),
        }
        return self._request("POST", "/distractions/detected", body)["id"]

    def end_distraction(self, distraction_id: int, at: datetime) -> None:
        self._request("POST", f"/distractions/{distraction_id}/end", {"at": at.isoformat()})

    def log_inactivity(self, minutes: int, started_at: datetime) -> None:
        body = {"inactive_minutes": max(1, min(180, minutes)), "timestamp": started_at.isoformat()}
        self._request("POST", "/distractions/inferred", body)


class LiveListener:
    """Keeps a WebSocket open and forwards each message to `on_message`; reconnects with backoff."""

    MAX_BACKOFF = 30.0

    def __init__(self, base_url: str, token: str, on_message: Callable[[dict], None], on_unauthorized=None) -> None:
        scheme = "wss" if base_url.startswith("https") else "ws"
        host = base_url.split("://", 1)[-1].rstrip("/")
        self.url = f"{scheme}://{host}/api/v1/ws?token={quote(token)}"
        self.on_message = on_message
        self.on_unauthorized = on_unauthorized or (lambda: None)
        self._stop = threading.Event()
        self._socket = None
        self._thread = threading.Thread(target=self._run, name="flowsense-live", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
        self._thread.join(timeout=3)

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                with connect(self.url, open_timeout=5, ping_interval=25) as socket:
                    self._socket = socket
                    backoff = 1.0
                    for raw in socket:
                        if isinstance(raw, str) and raw != "pong":
                            self.on_message(json.loads(raw))
                    if socket.close_code == 4401:
                        self.on_unauthorized()
                        return
            except (OSError, WebSocketException, ValueError) as error:
                logger.debug("live connection dropped: %s", error)
            finally:
                self._socket = None
            if self._stop.wait(backoff):
                return
            backoff = min(self.MAX_BACKOFF, backoff * 2)
