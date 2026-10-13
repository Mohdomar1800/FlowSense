"""End-to-end: real screen tracker + real server + real UI, with a scripted "screen".

The tracker is the same code the desktop app runs; only the window source and notifier are swapped
for scripted/recording versions so the scenario is repeatable.

Usage (server running at FLOWSENSE_URL, default http://127.0.0.1:8000):
    python e2e/agent_flow.py
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

from agent.tracker import FocusAgent  # noqa: E402
from agent.window_source import Window  # noqa: E402

BASE = os.environ.get("FLOWSENSE_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).parent / "shots"
OUT.mkdir(exist_ok=True)

VS_CODE = Window("Code.exe", "notes.py - FlowSense - Visual Studio Code")
CAT_VIDEO = Window("chrome.exe", "Funny cats compilation - YouTube - Google Chrome")
DISCORD = Window("Discord.exe", "#homework-help | Study Group - Discord")


def call(method: str, path: str, token: str | None = None, body: dict | None = None):
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


class ScriptedScreen:
    def __init__(self) -> None:
        self.window = VS_CODE

    def __call__(self) -> Window:
        return self.window


class RecordingNotifier:
    def __init__(self) -> None:
        self.titles: list[str] = []

    def notify(self, title: str, message: str) -> None:
        self.titles.append(title)


def wait_for(condition, timeout=8.0, message="condition"):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.2)
    raise AssertionError(f"timed out waiting for {message}")


def main() -> None:
    email = f"agent{int(time.time())}@example.com"
    call("POST", "/auth/register", body={"email": email, "password": "password123"})
    token = call(
        "POST", "/auth/login", body={"email": email, "password": "password123"}
    )["access_token"]
    call("PATCH", "/settings", token, {"distraction_grace_seconds": 2})
    call(
        "PATCH", "/auth/me", token, {"onboarded": True}
    )  # skip the first-run setup in the UI

    screen, notifier = ScriptedScreen(), RecordingNotifier()
    tracker = FocusAgent(
        BASE, notifier=notifier, get_window=screen, get_idle_seconds=lambda: 0.0
    )
    tracker.start()
    tracker.set_token(token)
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

        # Start a session: the tracker notices via the live connection and starts reporting.
        page.get_by_label("What are you working on?").fill("Linear algebra")
        page.get_by_role("button", name="Start focus session").click()
        activity = page.locator(".activity-line")
        expect(activity).to_contain_text("Visual Studio Code", timeout=8000)
        expect(activity).to_contain_text("On task")
        print("1. tracking started, VS Code = on task")

        # Drift to a cat video: after the 2 s grace, an alert appears and a notification is sent.
        screen.window = CAT_VIDEO
        expect(activity).to_contain_text("Off task", timeout=5000)
        alert = page.locator(".drift-alert")
        expect(alert).to_contain_text("You drifted to YouTube", timeout=8000)
        wait_for(
            lambda: "Back to focus?" in notifier.titles, message="desktop notification"
        )
        page.screenshot(path=OUT / "10_drift_alert.png")
        print("2. cat video -> alert + notification")

        # Back to work: the alert clears and the distraction gets a duration.
        time.sleep(2)
        screen.window = VS_CODE
        expect(alert).to_be_hidden(timeout=8000)
        youtube = call("GET", "/distractions", token)["items"][0]
        assert (
            youtube["event_type"] == "screen" and youtube["subject"] == "YouTube"
        ), youtube
        assert youtube["duration_seconds"] and youtube["duration_seconds"] >= 3, youtube
        print(
            f"3. back to VS Code -> alert cleared, distraction lasted {youtube['duration_seconds']}s"
        )

        # Discord is flagged by default; "Always allow" removes it and adds a rule.
        screen.window = DISCORD
        expect(alert).to_contain_text("You drifted to Discord", timeout=8000)
        page.get_by_role("button", name="Always allow Discord").click()
        expect(page.locator(".toast").last).to_contain_text("won't be flagged again")
        expect(alert).to_be_hidden()
        rules = call("GET", "/activity/rules", token)
        assert [(r["pattern"], r["kind"]) for r in rules] == [
            ("discord", "focus")
        ], rules
        notified = len(notifier.titles)
        time.sleep(4)  # staying on Discord must not re-alert
        assert call("GET", "/distractions", token)["total_count"] == 1
        screen.window = VS_CODE
        time.sleep(1.5)
        screen.window = DISCORD
        expect(activity).to_contain_text(
            "On task", timeout=5000
        )  # the rule now applies
        print("4. always-allow Discord -> no more alerts, rule active")

        # Paused: nothing is tracked.
        page.get_by_role("button", name="Pause", exact=True).click()
        screen.window = CAT_VIDEO
        time.sleep(4)
        assert call("GET", "/distractions", token)["total_count"] == 1
        assert len(notifier.titles) == notified
        print("5. paused -> screen not tracked")

        page.get_by_role("button", name="Resume", exact=True).click()
        page.get_by_role("button", name="Stop", exact=True).click()
        expect(page.locator(".toast").last).to_contain_text("Session saved")
        browser.close()

    tracker.stop()
    if errors:
        raise SystemExit("browser errors:\n" + "\n".join(errors))
    print("Agent flow OK. Notifications:", notifier.titles)


if __name__ == "__main__":
    main()
