"""End-to-end smoke test: drives the real UI in headless Chromium against a running server.

Usage (server running at FLOWSENSE_URL, default http://127.0.0.1:8000):
    pip install -r e2e/requirements.txt && python -m playwright install chromium
    python e2e/ui_smoke.py

Screenshots of each stage are written to e2e/shots/. Exits non-zero on any failure or browser error.
"""

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("FLOWSENSE_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).parent / "shots"
OUT.mkdir(exist_ok=True)
EMAIL = f"ui{int(time.time())}@example.com"

errors: list[str] = []


def watch(page):
    page.on(
        "console",
        lambda m: m.type == "error"
        and "status of 401" not in m.text
        and errors.append(f"console: {m.text}"),
    )
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))


with sync_playwright() as p:
    browser = p.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 820})
    page = ctx.new_page()
    watch(page)

    page.goto(BASE)
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    page.screenshot(path=OUT / "01_login.png")

    # Bad login shows an error
    page.get_by_label("Email").fill("nobody@example.com")
    page.get_by_label("Password").fill("wrong-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("alert")).to_contain_text("Invalid email or password")

    # Register
    page.get_by_role("button", name="Create an account").click()
    page.get_by_label("Email").fill(EMAIL)
    page.get_by_label("Password").fill("password123")
    page.get_by_role("button", name="Create account").click()

    # First-run onboarding: goal, tags, tracking
    expect(page.get_by_role("heading", name="Welcome to FlowSense")).to_be_visible()
    page.screenshot(path=OUT / "02a_onboarding_welcome.png")
    page.get_by_role("button", name="Let's go").click()
    page.get_by_role("radio", name="1 h Steady habit").click()
    expect(page.get_by_role("radio", name="1 h Steady habit")).to_have_attribute(
        "aria-checked", "true"
    )
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Coding").click()
    page.get_by_label("Custom tag").fill("Linear Algebra")
    page.get_by_role("button", name="Add", exact=True).click()
    expect(page.get_by_role("button", name="Linear Algebra")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.screenshot(path=OUT / "02b_onboarding_tags.png")
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Back").click()  # going back keeps choices
    expect(page.get_by_role("button", name="Coding")).to_have_attribute(
        "aria-pressed", "true"
    )
    page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Finish").click()
    expect(page.get_by_role("button", name="Start focus session")).to_be_visible()
    expect(page.locator(".progress").locator("..")).to_contain_text("Goal 1h 00m")
    expect(page.locator(".live-status")).to_have_attribute("data-status", "online")
    page.screenshot(path=OUT / "02_home_idle.png")

    # Create a tag in settings
    page.get_by_role("link", name="Settings").click()
    expect(page.get_by_label("Tag name for Linear Algebra")).to_be_visible()
    expect(page.get_by_label("Tag name for Coding")).to_be_visible()
    expect(page.get_by_label("Tag name for Study")).to_be_visible()
    page.get_by_label("Daily focus goal (minutes)").fill("60")
    page.get_by_role("button", name="Save").nth(1).click()
    expect(page.locator(".toast").last).to_contain_text("Settings saved")
    page.screenshot(path=OUT / "03_settings.png")

    # Start a session with intent + tag
    page.get_by_role("link", name="Focus", exact=True).click()
    page.get_by_label("What are you working on?").fill("Lecture 5: eigenvalues")
    page.get_by_label("Tag").select_option(label="Linear Algebra")
    page.get_by_role("button", name="Start focus session").click()
    expect(page.locator(".focus-status")).to_have_text("Focusing")
    time.sleep(3.2)
    timer = page.locator("[data-timer]").inner_text()
    assert timer >= "00:02", timer
    expect(page.locator(".focus-intent")).to_contain_text("Lecture 5: eigenvalues")
    expect(page.get_by_label("What are you working on?")).to_be_hidden()
    expect(page.locator(".session-item .small").first).to_contain_text("Started")
    page.screenshot(path=OUT / "04_home_active.png")

    # Distraction, pause (via Space key), resume, stop
    page.get_by_role("button", name="I got distracted").click()
    expect(page.locator(".toast").last).to_contain_text("Distraction logged")
    expect(page.locator(".metric-value").nth(2)).to_have_text("1")
    page.locator("body").press("Space")
    expect(page.locator(".focus-status")).to_have_text("Paused")
    expect(page.locator(".pause-note")).to_contain_text("On a break")
    page.screenshot(path=OUT / "05_home_paused.png")
    page.get_by_role("button", name="Resume", exact=True).click()
    expect(page.locator(".focus-status")).to_have_text("Focusing")
    page.get_by_role("button", name="Stop", exact=True).click()
    expect(page.locator(".toast").last).to_contain_text("Session saved")
    expect(page.locator(".focus-status")).to_have_text("Ready")
    expect(page.locator(".session-item")).to_have_count(1)
    expect(page.locator(".session-item .title")).to_have_text("Lecture 5: eigenvalues")
    page.screenshot(path=OUT / "06_home_after_stop.png")

    page.locator(".session-item").first.click()
    dialog = page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    expect(dialog.locator(".timeline li")).to_have_count(
        5
    )  # started, distraction, paused, resumed, stopped
    page.screenshot(path=OUT / "06b_session_dialog.png")
    dialog.get_by_label("Working on").fill("Lecture 5: eigenvectors")
    dialog.get_by_role("button", name="Save").click()
    expect(page.locator(".session-item .title")).to_have_text("Lecture 5: eigenvectors")
    page.locator(".session-item").first.press("Enter")  # keyboard opens it too
    expect(page.get_by_role("dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.get_by_role("dialog")).to_have_count(0)
    expect(page.locator(".focus-status")).to_have_text(
        "Ready"
    )  # Space/Enter there never toggles the session

    # Reload keeps the user signed in; a second window sees live updates
    page.reload()
    expect(page.get_by_role("button", name="Start focus session")).to_be_visible()
    other = ctx.new_page()
    watch(other)
    other.goto(BASE)
    expect(other.locator(".live-status")).to_have_attribute("data-status", "online")
    page.get_by_role("button", name="Start focus session").click()
    expect(other.locator(".focus-status")).to_have_text(
        "Focusing"
    )  # pushed over the WebSocket
    other.get_by_role("button", name="Stop", exact=True).click()
    expect(page.locator(".focus-status")).to_have_text("Ready")
    other.close()

    # Reports page and mobile + dark layouts
    page.get_by_role("link", name="Reports").click()
    expect(page.get_by_role("heading", name="Reports")).to_be_visible()
    page.get_by_role("link", name="Focus", exact=True).click()

    mobile = browser.new_context(
        viewport={"width": 390, "height": 800},
        color_scheme="dark",
        storage_state=ctx.storage_state(),
    )
    mpage = mobile.new_page()
    watch(mpage)
    mpage.goto(BASE)
    expect(mpage.get_by_role("button", name="Start focus session")).to_be_visible()
    width = mpage.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"horizontal scroll on mobile: {width}px"
    mpage.screenshot(path=OUT / "07_mobile_dark.png", full_page=True)

    # Appearance: explicit dark theme, then back to system
    page.get_by_role("link", name="Settings").click()
    page.get_by_role("radio", name="Dark").click()
    assert page.evaluate("document.documentElement.dataset.theme") == "dark"
    page.screenshot(path=OUT / "08_settings_dark.png", full_page=True)
    page.reload()
    assert (
        page.evaluate("document.documentElement.dataset.theme") == "dark"
    )  # remembered
    page.get_by_role("radio", name="System").click()
    assert page.evaluate("document.documentElement.dataset.theme") is None

    # Change password: this window stays signed in
    page.get_by_label("Current password").fill("password123")
    page.get_by_label("New password").fill("password456")
    page.get_by_role("button", name="Change password").click()
    expect(page.locator(".toast").last).to_contain_text("Password changed")
    page.reload()
    expect(page.get_by_role("heading", name="Settings")).to_be_visible()

    # Sign out and back in with the new password
    page.get_by_role("button", name="Sign out").click()
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    page.get_by_label("Email").fill(EMAIL)
    page.get_by_label("Password").fill("password456")
    page.get_by_role("button", name="Sign in").click()
    # Back on the page we left (Settings), and no onboarding the second time.
    expect(page.get_by_role("heading", name="Settings")).to_be_visible()
    expect(page.get_by_role("heading", name="Welcome to FlowSense")).to_have_count(0)

    # Delete the test account (cleans up after this run)
    page.get_by_role("link", name="Settings").click()
    page.once("dialog", lambda d: d.accept("password456"))
    page.get_by_role("button", name="Delete…").click()
    expect(page.get_by_role("heading", name="Welcome back")).to_be_visible()
    expect(page.get_by_role("alert")).to_contain_text("Your account was deleted")
    browser.close()

if errors:
    print("ERRORS:\n" + "\n".join(errors))
    sys.exit(1)
print("UI flow OK, screenshots in", OUT)
