"""Where the desktop app keeps its files, its per-user configuration, and logging.

Works both from a source checkout and when packaged with PyInstaller (sys.frozen), where bundled
files live under sys._MEIPASS.

Per-user configuration lives in a small env-style file:
    Windows: %APPDATA%\\FlowSense\\config.env     macOS: ~/Library/Application Support/FlowSense/config.env
    Linux:   ~/.config/FlowSense/config.env
It is created on first run with a randomly generated JWT secret, so an installed app never runs with
the insecure development default. Edit it to point FlowSense at a different database.
"""

import logging
import logging.handlers
import os
import secrets
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
# Root of the bundled/checked-out project: contains backend/, frontend/ and desktop/ (or their bundled copies).
ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

DEFAULT_CONFIG = """\
# FlowSense desktop configuration. Lines are KEY=value; environment variables override them.

# PostgreSQL (required). Run it with `docker compose up -d postgres` or install PostgreSQL natively.
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=flowsense
POSTGRES_USER=flowsense
POSTGRES_PASSWORD=flowsense

# Redis is optional (caching and live updates across processes). Set to false if you don't run it.
REDIS_ENABLED=true
REDIS_HOST=127.0.0.1
REDIS_PORT=6379

# Generated on first run. Keep it secret: anyone with it can sign in as any user.
JWT_SECRET_KEY={secret}
"""


def _base_dir(kind: str) -> Path:
    if sys.platform == "win32":
        env = "LOCALAPPDATA" if kind == "local" else "APPDATA"
        return Path(os.environ.get(env, Path.home() / "AppData" / ("Local" if kind == "local" else "Roaming")))
    if sys.platform == "darwin":
        return Path.home() / "Library" / ("Logs" if kind == "local" else "Application Support")
    return Path(
        os.environ.get(
            "XDG_STATE_HOME" if kind == "local" else "XDG_CONFIG_HOME",
            Path.home() / (".local/state" if kind == "local" else ".config"),
        )
    )


def config_dir() -> Path:
    path = _base_dir("roaming") / "FlowSense"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_dir() -> Path:
    path = _base_dir("local") / "FlowSense" / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return config_dir() / "config.env"


def ensure_config(path: Path | None = None) -> Path:
    """Create the config file with a fresh secret if it doesn't exist yet."""
    path = path or config_path()
    if not path.exists():
        path.write_text(DEFAULT_CONFIG.format(secret=secrets.token_urlsafe(48)), encoding="utf-8")
        try:
            path.chmod(0o600)  # owner-only where the OS supports it
        except OSError:
            pass
    return path


def parse_config(text: str) -> dict[str, str]:
    values = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip().upper()] = value.strip().strip('"').strip("'")
    return values


def load_config(path: Path | None = None) -> dict[str, str]:
    """Apply the config file to os.environ (existing environment variables win) and return what it contained."""
    values = parse_config(ensure_config(path).read_text(encoding="utf-8"))
    for key, value in values.items():
        os.environ.setdefault(key, value)
    if FROZEN:
        # Bundled copies of the UI; the backend's default (repo-relative) path doesn't exist inside the bundle.
        os.environ.setdefault("FRONTEND_DIR", str(FRONTEND_DIR))
        os.environ.setdefault("APP_ENV", "production")
    return values


def attach_console() -> None:
    """A windowed (no-console) build has no stdout. When started from a terminal (e.g. `FlowSense.exe --check`),
    borrow that terminal's console so output is visible."""
    if sys.stdout is not None or sys.platform != "win32":
        return
    import ctypes

    if ctypes.windll.kernel32.AttachConsole(-1):  # -1: the parent process's console
        sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stderr = sys.stdout


def setup_logging(debug: bool = False) -> Path:
    """Log to a rotating file (a windowed app has no console) and, from source, to the console too."""
    logfile = log_dir() / "flowsense.log"
    handlers: list[logging.Handler] = [
        logging.handlers.RotatingFileHandler(logfile, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    ]
    if not FROZEN and sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    return logfile
