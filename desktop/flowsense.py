"""FlowSense desktop app.

Opens the FlowSense UI in a native window (pywebview, using the OS's built-in browser engine) and runs
the focus agent (screen + camera tracking) alongside it.

- If a FlowSense server is already running at --url (for example the Docker one), the window uses it.
- Otherwise an embedded server is started inside this process: migrations are applied, the API
  runs on a background thread, and it shuts down when the window closes.

PostgreSQL must be reachable either way (Redis is optional); see the config file printed by --check.

    python desktop/flowsense.py            # from a source checkout
    FlowSense.exe                          # packaged
    FlowSense.exe --check                  # start the server, verify database + UI, exit (no window)
"""

import argparse
import html
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # `agent` and `appconfig` from a checkout

import appconfig  # noqa: E402

DEFAULT_URL = os.environ.get("FLOWSENSE_URL", "http://127.0.0.1:8000")
STARTUP_TIMEOUT_SECONDS = 30

logger = logging.getLogger("flowsense.desktop")


# ---------------------------------------------------------------------------
# Server discovery
# ---------------------------------------------------------------------------


def fetch(url: str, timeout: float = 1.5) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except (urllib.error.URLError, OSError):
        return 0, b""


def fetch_json(url: str, timeout: float = 1.5) -> tuple[int, dict | None]:
    status, body = fetch(url, timeout)
    try:
        return status, json.loads(body or b"null")
    except ValueError:
        return status, None


def is_flowsense(url: str) -> bool:
    status, body = fetch_json(f"{url}/health")
    return status == 200 and body == {"status": "ok"}


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1" if host == "localhost" else host, port)) == 0


def wait_until_up(url: str, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_flowsense(url):
            return True
        time.sleep(0.2)
    return False


class EmbeddedServer:
    """Runs the FastAPI app with uvicorn on a background thread of this process."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        self._server = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # The backend resolves its .env and alembic.ini relative to backend/.
        os.chdir(appconfig.BACKEND_DIR)
        if not appconfig.FROZEN:
            sys.path.insert(0, str(appconfig.BACKEND_DIR))  # packaged builds already contain the `app` package

        from alembic import command
        from alembic.config import Config

        logger.info("applying database migrations")
        alembic_config = Config(str(appconfig.BACKEND_DIR / "alembic.ini"))
        alembic_config.set_main_option("script_location", str(appconfig.BACKEND_DIR / "alembic"))
        command.upgrade(alembic_config, "head")

        import uvicorn
        from app.main import app

        # log_config=None: use our logging; uvicorn's default writes to a console a windowed app doesn't have.
        config = uvicorn.Config(app, host=self.host, port=self.port, log_config=None, log_level="warning")
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="flowsense-api", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=5)


def connect_or_start(url: str) -> tuple[EmbeddedServer | None, str | None]:
    """Use a running server at `url`, or start one. Returns (embedded server or None, error message or None)."""
    if is_flowsense(url):
        logger.info("using running FlowSense server at %s", url)
        return None, None
    parsed = urlparse(url)
    if parsed.hostname not in {"127.0.0.1", "localhost"}:
        return None, f"No FlowSense server answered at {url}."
    port = parsed.port or 8000
    # Otherwise uvicorn fails to bind on its thread and we would only notice after the startup timeout.
    if port_in_use(parsed.hostname, port):
        return None, (
            f"Port {port} is already used by another program. Close that program, or start FlowSense on "
            f"another port, for example: --url http://127.0.0.1:{port + 10}"
        )
    logger.info("starting embedded server on %s", url)
    embedded = EmbeddedServer(parsed.hostname, port)
    try:
        embedded.start()
        if not wait_until_up(url, STARTUP_TIMEOUT_SECONDS):
            raise RuntimeError("the server did not start in time")
    except Exception as exc:  # most often: the database isn't running
        logger.exception("embedded server failed to start")
        embedded.stop()
        return None, f"{type(exc).__name__}: {exc}"
    return embedded, None


def database_problem(url: str) -> str | None:
    status, body = fetch_json(f"{url}/ready")
    if status == 200:
        return None
    return f"The FlowSense server is running, but the database is {(body or {}).get('database', 'unreachable')}."


# ---------------------------------------------------------------------------
# Self-check (no window)
# ---------------------------------------------------------------------------


def run_check(url: str) -> int:
    """Start (or find) the server, then verify the database, the API and the bundled UI. Prints a report."""
    print(f"Config file: {appconfig.config_path()}")
    print(f"Log file:    {appconfig.log_dir() / 'flowsense.log'}")
    embedded, error = connect_or_start(url)
    try:
        checks = [("server", error is None, error or url)]
        if error is None:
            problem = database_problem(url)
            checks.append(("database", problem is None, problem or "ready"))
            status, page = fetch(f"{url}/")
            checks.append(("web UI", status == 200 and b"<title>FlowSense</title>" in page, f"HTTP {status}"))
            status, _ = fetch(f"{url}/vendor/chart.umd.min.js")
            checks.append(("chart library", status == 200, f"HTTP {status}"))
            status, body = fetch_json(f"{url}/api/v1/auth/me")
            checks.append(("API auth", status == 401, f"HTTP {status} without a token"))
        from agent.camera.worker import camera_supported

        checks.append(
            ("camera support", camera_supported(), "OpenCV available" if camera_supported() else "OpenCV missing")
        )
        for name, ok, detail in checks:
            print(f"  [{'ok' if ok else 'FAIL'}] {name}: {detail}")
        passed = all(ok for _, ok, _ in checks)
        print("FlowSense check passed." if passed else "FlowSense check FAILED.")
        return 0 if passed else 1
    finally:
        if embedded is not None:
            embedded.stop()


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


def error_page(title: str, message: str) -> str:
    config = html.escape(str(appconfig.config_path()))
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
    body {{ font-family: system-ui, sans-serif; display: grid; place-items: center; min-height: 100vh; margin: 0;
           background: #f6f7fb; color: #171a26; }}
    main {{ max-width: 560px; padding: 32px; background: #fff; border: 1px solid #e3e6ef; border-radius: 14px; }}
    code {{ display: block; margin: 12px 0; padding: 10px; background: #f0f2f8; border-radius: 8px;
            word-break: break-all; }}
    </style></head><body><main><h2>{html.escape(title)}</h2><p>{html.escape(message)}</p>
    <p>If it's about the database, make sure PostgreSQL is running, for example:</p>
    <code>docker compose up -d postgres redis</code>
    <p>Database settings are in:</p><code>{config}</code>
    </main></body></html>"""


def build_agent(url: str):
    from agent.camera.worker import CameraWorker, camera_supported
    from agent.notify import DesktopNotifier
    from agent.tracker import FocusAgent

    notifier = DesktopNotifier()
    camera = CameraWorker(notifier) if camera_supported() else None
    if camera is None:
        logger.info("OpenCV not installed: camera tracking unavailable")
    return FocusAgent(url, notifier=notifier, camera=camera)


class DesktopBridge:
    """Methods the web UI can call as window.pywebview.api.<name>(...)."""

    def __init__(self, agent) -> None:
        self._agent = agent

    def set_token(self, token: str | None) -> bool:
        """The UI hands over the signed-in user's token (or None on sign-out) so the agent can act for them."""
        threading.Thread(target=self._agent.set_token, args=(token or None,), daemon=True).start()
        return True

    def capabilities(self) -> dict:
        return {"screen_tracking": True, "camera_tracking": self._agent.camera is not None, "platform": sys.platform}

    def info(self) -> dict:
        return {"config_file": str(appconfig.config_path()), "log_dir": str(appconfig.log_dir())}

    def camera_status(self) -> dict:
        camera = self._agent.camera
        return {"available": camera is not None, "in_use": bool(camera and camera.camera_open)}


def run_window(url: str, debug: bool) -> int:
    import webview  # imported late so --check and --help work without the GUI toolkit

    embedded, error = connect_or_start(url)
    if error is None:
        problem = database_problem(url)
        page = {"html": error_page("Database unavailable", problem)} if problem else {"url": url}
    else:
        page = {"html": error_page("FlowSense couldn't start", error)}

    webview.settings["ALLOW_DOWNLOADS"] = True  # report exports ("Export Markdown")
    agent = build_agent(url)
    agent.start()
    webview.create_window("FlowSense", width=1180, height=780, min_size=(380, 560), js_api=DesktopBridge(agent), **page)
    storage = appconfig.config_dir() / "webview"  # keeps you signed in between launches
    storage.mkdir(exist_ok=True)
    try:
        webview.start(private_mode=False, storage_path=str(storage), debug=debug)
    finally:
        agent.stop()
        if embedded is not None:
            embedded.stop()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="FlowSense desktop app")
    parser.add_argument("--url", default=DEFAULT_URL, help="FlowSense server URL (default: %(default)s)")
    parser.add_argument("--debug", action="store_true", help="enable the web inspector and verbose logs")
    parser.add_argument("--check", action="store_true", help="start the server, verify everything works, and exit")
    if "--check" in sys.argv or "--help" in sys.argv or "-h" in sys.argv:
        appconfig.attach_console()
    args = parser.parse_args()

    appconfig.setup_logging(args.debug)
    appconfig.load_config()
    url = args.url.rstrip("/")
    try:
        return run_check(url) if args.check else run_window(url, args.debug)
    except Exception:
        logger.exception("FlowSense crashed")
        raise


if __name__ == "__main__":
    sys.exit(main())
