"""End-to-end: camera phone detection through the real agent, server and UI.

The camera and the vision models are replaced by a scripted feed of observations (what the models
would report), so this runs without a webcam and checks everything downstream of the models:
episode detection, the "Phone down?" alert, dismissal, and the camera being released on pause.

Usage (server running at FLOWSENSE_URL, default http://127.0.0.1:8000):
    python e2e/camera_flow.py
"""

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop"))

from agent.camera.phone_monitor import Box, Detection, Observation  # noqa: E402
from agent.camera.worker import CameraWorker  # noqa: E402
from agent.tracker import FocusAgent  # noqa: E402

BASE = os.environ.get("FLOWSENSE_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).parent / "shots"
OUT.mkdir(exist_ok=True)

FACE = Box(0.4, 0.2, 0.2, 0.3)
WORKING = Observation(face=FACE, head_pitch=0.55)
WRITING_NOTES = Observation(face=FACE, head_pitch=0.75)
ON_PHONE = Observation(
    face=FACE, head_pitch=0.78, phones=(Detection(Box(0.42, 0.62, 0.1, 0.15), 0.85),)
)


def call(method, path, token=None, body=None):
    request = urllib.request.Request(
        f"{BASE}/api/v1{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read()
        return json.loads(raw) if raw else None


class ScriptedCamera:
    """Stands in for both the webcam and the models: returns whatever `scene` is set to."""

    def __init__(self) -> None:
        self.scene = WORKING
        self.opened = 0
        self.released = 0

    def open(self, index):
        self.opened += 1
        camera = self

        class Capture:
            def grab(self):
                return True

            def read(self):
                return (
                    True,
                    object(),
                )  # any non-empty frame; the scripted analyzer ignores it

            def release(self):
                camera.released += 1

        return Capture()

    def analyze(self, frame):
        return self.scene


class RecordingNotifier:
    def __init__(self) -> None:
        self.titles: list[str] = []

    def notify(self, title, message):
        self.titles.append(title)


def wait_for(condition, timeout=10.0, what="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {what}")


def main() -> None:
    email = f"camera{int(time.time())}@example.com"
    call("POST", "/auth/register", body={"email": email, "password": "password123"})
    token = call(
        "POST", "/auth/login", body={"email": email, "password": "password123"}
    )["access_token"]
    call(
        "PATCH",
        "/settings",
        token,
        {"camera_tracking_enabled": True, "screen_tracking_enabled": False},
    )
    call(
        "PATCH", "/auth/me", token, {"onboarded": True}
    )  # skip the first-run setup in the UI

    camera, notifier = ScriptedCamera(), RecordingNotifier()
    worker = CameraWorker(
        notifier, analyzer_factory=lambda: camera, capture_factory=camera.open
    )
    agent = FocusAgent(
        BASE,
        notifier=notifier,
        camera=worker,
        get_window=lambda: None,
        get_idle_seconds=lambda: 0,
    )
    agent.start()
    agent.set_token(token)
    errors: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 820})
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(
            f"localStorage.setItem('flowsense.token', {json.dumps(token)})"
        )
        page.goto(BASE)

        time.sleep(1.5)
        assert camera.opened == 0, "camera opened before a session started"
        page.get_by_role("button", name="Start focus session").click()
        wait_for(
            lambda: camera.opened == 1, what="camera to open when the session starts"
        )
        print("1. session started -> camera opened")

        # A minute of writing notes: looking down, no phone. Must not trigger.
        camera.scene = WORKING
        time.sleep(4)  # learn the normal head angle
        camera.scene = WRITING_NOTES
        time.sleep(8)
        assert call("GET", "/distractions", token)["total_count"] == 0
        assert notifier.titles == []
        print("2. writing notes (looking down, no phone) -> nothing flagged")

        # Phone use: alert after a few seconds, with no "Always allow" option.
        camera.scene = ON_PHONE
        alert = page.locator(".drift-alert")
        expect(alert).to_contain_text("Phone down?", timeout=12000)
        expect(alert.get_by_role("button", name="Not a distraction")).to_be_visible()
        expect(alert.get_by_role("button", name="Always allow Phone")).to_have_count(0)
        assert "Phone down?" in notifier.titles
        page.screenshot(path=OUT / "11_phone_alert.png")
        print("3. phone in use -> 'Phone down?' alert + notification")

        # Put it away: the episode ends with a duration and the alert clears.
        time.sleep(2)
        camera.scene = WORKING
        expect(alert).to_be_hidden(timeout=12000)
        phone = call("GET", "/distractions", token)["items"][0]
        assert phone["event_type"] == "camera" and phone["subject"] == "Phone", phone
        assert phone["duration_seconds"] and phone["duration_seconds"] >= 3, phone
        print(
            f"4. phone put away -> alert cleared, phone use lasted {phone['duration_seconds']}s"
        )

        # Dismissing ("I needed a 2FA code") stops re-flagging while the phone stays in hand.
        camera.scene = ON_PHONE
        expect(alert).to_contain_text("Phone down?", timeout=12000)
        page.get_by_role("button", name="Not a distraction").click()
        expect(alert).to_be_hidden()
        time.sleep(6)
        assert call("GET", "/distractions", token)["total_count"] == 1
        print("5. dismissed -> removed and not re-flagged")

        # Pausing releases the camera.
        page.get_by_role("button", name="Pause", exact=True).click()
        wait_for(
            lambda: camera.released >= 1 and not worker.camera_open,
            what="camera release on pause",
        )
        print("6. paused -> camera released")

        page.get_by_role("button", name="Resume", exact=True).click()
        wait_for(lambda: worker.camera_open, what="camera to reopen on resume")
        page.get_by_role("button", name="Stop", exact=True).click()
        wait_for(lambda: not worker.camera_open, what="camera release on stop")
        print("7. resumed -> reopened; stopped -> released")
        browser.close()

    agent.stop()
    if errors:
        raise SystemExit("browser errors:\n" + "\n".join(errors))
    print("Camera flow OK. Notifications:", notifier.titles)


if __name__ == "__main__":
    main()
