"""Reports in a real browser with the seeded demo account (python -m scripts.seed_demo_data).

Checks the history list, filters, the report view, Markdown export, the print (PDF) layout,
and the one-pane mobile flow. Screenshots go to e2e/shots/.
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


with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, accept_downloads=True
    )
    page = context.new_page()
    watch(page)
    page.goto(BASE)
    page.get_by_label("Email").fill("demo@example.com")
    page.get_by_label("Password").fill("demo-password")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("button", name="Start focus session")).to_be_visible()

    page.get_by_role("link", name="Reports").click()
    items = page.locator(".report-item")
    expect(items.first).to_be_visible()
    count = items.count()
    assert count >= 10, f"expected the seeded report history, got {count}"

    # On a wide screen the newest report opens right away, and the URL points at it.
    report = page.locator(".report")
    expect(report.get_by_role("heading", name="Goal for tomorrow")).to_be_visible()
    assert "#/reports/" in page.url
    page.screenshot(path=OUT / "30_report_daily.png", full_page=True)

    # Weekly filter and a weekly report
    page.get_by_role("tab", name="Weekly").click()
    expect(items.first).to_contain_text("Week of")
    items.first.click()
    expect(report.get_by_role("heading", name="Goal for next week")).to_be_visible()
    expect(report.locator(".week-bar")).to_have_count(7)
    page.screenshot(path=OUT / "31_report_weekly.png", full_page=True)

    # Deep link survives a reload
    url = page.url
    title = report.locator(".report-title").inner_text()
    page.reload()
    expect(page.locator(".report .report-title")).to_have_text(title)
    assert page.url == url

    # Markdown export downloads a file
    with page.expect_download() as download_info:
        page.get_by_role("button", name="Export Markdown").click()
    download = download_info.value
    assert download.suggested_filename.startswith(
        "flowsense-weekly-report-"
    ), download.suggested_filename
    text = Path(download.path()).read_text(encoding="utf-8")
    assert (
        text.startswith("# Weekly report: Week of") and "## Goal for next week" in text
    )

    # Print layout: only the report
    page.emulate_media(media="print")
    expect(page.locator(".sidebar")).to_be_hidden()
    expect(page.locator(".report-list-pane")).to_be_hidden()
    expect(page.get_by_role("button", name="Export Markdown")).to_be_hidden()
    page.screenshot(path=OUT / "32_report_print.png", full_page=True)
    page.emulate_media(media="screen")

    # Mobile: list first, open a report, go back
    mobile = browser.new_context(
        viewport={"width": 390, "height": 844},
        color_scheme="dark",
        storage_state=context.storage_state(),
    )
    mpage = mobile.new_page()
    watch(mpage)
    mpage.goto(f"{BASE}/#/reports")
    expect(mpage.locator(".report-item").first).to_be_visible()
    expect(mpage.locator(".report")).to_have_count(0)
    mpage.locator(".report-item").first.click()
    expect(mpage.locator(".report")).to_be_visible()
    expect(mpage.locator(".report-list-pane")).to_be_hidden()
    width = mpage.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, f"horizontal scroll on mobile: {width}px"
    mpage.screenshot(path=OUT / "33_report_mobile_dark.png", full_page=True)
    mpage.get_by_role("button", name="‹ All reports").click()
    expect(mpage.locator(".report-list-pane")).to_be_visible()
    browser.close()

if errors:
    print("ERRORS:\n" + "\n".join(errors))
    sys.exit(1)
print(f"Reports OK ({count} reports), screenshots in {OUT}")
