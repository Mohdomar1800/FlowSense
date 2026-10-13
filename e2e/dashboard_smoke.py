"""Dashboard in a real browser with the seeded demo account (python -m scripts.seed_demo_data).

Checks each period, navigation, the chart actually rendering, mobile/dark layout, and no browser errors.
Screenshots go to e2e/shots/.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = os.environ.get("FLOWSENSE_URL", "http://127.0.0.1:8000")
OUT = Path(__file__).parent / "shots"
OUT.mkdir(exist_ok=True)
errors: list[str] = []


def watch(page):
    page.on(
        "console", lambda m: m.type == "error" and errors.append(f"console: {m.text}")
    )
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))


def chart_has_pixels(page) -> bool:
    """True if the trend chart canvas has been drawn on (not blank)."""
    return page.evaluate(
        """() => {
            const canvas = document.querySelector('.chart-box canvas');
            if (!canvas || !canvas.width) return false;
            const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
            for (let i = 3; i < data.length; i += 4) if (data[i] !== 0) return true;
            return false;
        }"""
    )


with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    watch(page)
    page.goto(BASE)
    page.get_by_label("Email").fill("demo@example.com")
    page.get_by_label("Password").fill("demo-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("button", name="Start focus session")).to_be_visible()

    page.get_by_role("link", name="Dashboard").click()
    page.get_by_role("tab", name="Month").click()
    expect(page.locator(".kpi").first).to_contain_text("Focus time")
    # The app's CSP forbids eval, so poll with evaluate() instead of wait_for_function().
    for _ in range(50):
        if page.evaluate("typeof window.Chart !== 'undefined'"):
            break
        page.wait_for_timeout(100)
    page.wait_for_timeout(600)
    assert chart_has_pixels(page), "month chart did not render"
    expect(
        page.locator(".heatmap .heat-cell[data-empty='false']").first
    ).to_be_visible()
    expect(page.get_by_role("heading", name="Top distractions")).to_be_visible()
    page.screenshot(path=OUT / "20_dashboard_month.png", full_page=True)

    # Previous month, then back
    label = page.locator(".range-label").inner_text()
    page.get_by_role("button", name="Previous period").click()
    expect(page.locator(".range-label")).not_to_have_text(label)
    page.get_by_role("button", name="Next period").click()
    expect(page.locator(".range-label")).to_have_text(label)
    expect(page.get_by_role("button", name="Next period")).to_be_disabled()

    page.get_by_role("tab", name="Week").click()
    expect(page.get_by_role("tab", name="Week")).to_have_attribute(
        "aria-selected", "true"
    )
    page.wait_for_timeout(600)
    page.screenshot(path=OUT / "21_dashboard_week.png", full_page=True)

    # A past day with data (the demo seed covers the previous two weeks)
    page.get_by_role("tab", name="Day").click()
    hourly = page.get_by_role("heading", name="Focus by hour")
    # Click "previous" quickly several times: only the newest response may render (no out-of-order data).
    expected = page.locator(".range-label").inner_text()
    for _ in range(4):
        page.get_by_role("button", name="Previous period").click()
    page.wait_for_timeout(2000)
    shown = page.locator(".range-label").inner_text()
    assert shown != expected, "range did not move"
    for _ in range(7):  # then step back calmly to the most recent day with sessions
        if hourly.count():
            break
        before = page.locator(".range-label").inner_text()
        page.get_by_role("button", name="Previous period").click()
        expect(page.locator(".range-label")).not_to_have_text(before)
    expect(hourly).to_be_visible()
    page.wait_for_timeout(600)
    assert chart_has_pixels(page), "day chart did not render"
    page.screenshot(path=OUT / "22_dashboard_day.png", full_page=True)

    # The chosen period is remembered across visits
    page.get_by_role("link", name="Focus", exact=True).click()
    page.get_by_role("link", name="Dashboard").click()
    expect(page.get_by_role("tab", name="Day")).to_have_attribute(
        "aria-selected", "true"
    )

    # Insights page and the tip on Home
    page.get_by_role("link", name="Insights").click()
    expect(page.locator(".insight").first).to_be_visible()
    expect(page.locator(".insight-evidence").first).not_to_be_empty()
    page.screenshot(path=OUT / "24_insights.png", full_page=True)
    page.get_by_role("link", name="Focus", exact=True).click()
    expect(page.get_by_role("heading", name="Tip for you")).to_be_visible()
    page.screenshot(path=OUT / "25_home_tip.png")

    mobile = browser.new_context(
        viewport={"width": 390, "height": 844},
        color_scheme="dark",
        storage_state=context.storage_state(),
    )
    mpage = mobile.new_page()
    watch(mpage)
    mpage.goto(f"{BASE}/#/dashboard")
    mpage.get_by_role("tab", name="Month").click()
    expect(mpage.locator(".kpi").first).to_be_visible()
    mpage.wait_for_timeout(800)
    width = mpage.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"horizontal scroll on mobile: {width}px"
    mpage.screenshot(path=OUT / "23_dashboard_mobile_dark.png", full_page=True)
    browser.close()

if errors:
    print("ERRORS:\n" + "\n".join(errors))
    sys.exit(1)
print("Dashboard OK, screenshots in", OUT)
