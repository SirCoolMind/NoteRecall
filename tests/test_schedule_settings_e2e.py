"""Browser checks for the schedule (row anatomy, search, remembered position) and the settings modal.

Meetings are generated into the temp data dir (never data/). Skips with the other e2e tests when
Playwright's Chromium is missing.
"""

import json
import re
from datetime import datetime, timedelta

import pytest

from conftest import CANNED_SEGMENTS, make_wav_bytes
from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect

pytestmark = pytest.mark.e2e


def seed(data_dir, count=45):
    """`count` finished meetings, newest first by index; every third one has a summary.md."""
    base = datetime(2026, 9, 28, 10, 0, 0)
    for i in range(count):
        mid = f"seed-{i:03d}"
        d = data_dir / mid
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({
            "id": mid, "title": f"Weekly sync {i:03d}" if i % 5 else f"Budget review {i:03d}",
            "created": (base - timedelta(days=i * 2)).isoformat(timespec="seconds"),
            "audio_file": "audio.wav", "status": "done", "progress": 100,
            "duration": 6727.0 if i == 0 else 600.0 + i, "speaker_names": {}, "num_speakers": 2}), encoding="utf-8")
        (d / "audio.wav").write_bytes(make_wav_bytes())
        (d / "transcript.json").write_text(json.dumps(CANNED_SEGMENTS), encoding="utf-8")
        if i % 3 == 0:
            (d / "summary.md").write_text(f"## Overview\nDiscussed rollout item {i:03d} and owners.", encoding="utf-8")


def rows(page):
    return page.locator("li.row")


def test_row_shows_length_stamp_summary_and_open_button(live_server, browser_page, data_dir):  # noqa: F811
    seed(data_dir, 4)
    page = browser_page
    page.goto(live_server + "/")
    first = rows(page).first
    expect(first.locator(".row__time")).to_have_text(re.compile(r"1\s*h\s*52\s*m"))
    expect(first.locator("time")).to_have_text(re.compile(r"28 Sep\w* 2026 \S 10:00"))
    expect(first.locator(".row__qs-label")).to_have_text("Quick summary")
    expect(first.locator(".row__qs-text")).to_contain_text("Discussed rollout item 000")
    expect(rows(page).nth(1).locator(".row__qs-text")).to_have_text("Not available yet")   # every row has the same shape
    eye = first.locator("a.row__eye")
    expect(eye).to_have_attribute("aria-label", "Open Budget review 000")
    expect(eye).to_have_attribute("href", "#/m/seed-000")
    box = eye.bounding_box()
    assert box["width"] >= 44 and box["height"] >= 44


def test_search_filters_and_survives_open_and_back(live_server, browser_page, data_dir):  # noqa: F811
    seed(data_dir, 45)
    page = browser_page
    page.set_viewport_size({"width": 1280, "height": 800})
    page.goto(live_server + "/")

    # Progressive list: 30 finished rows, then Show more.
    expect(rows(page)).to_have_count(30)
    expect(page.get_by_role("button", name="Show more (15 left)")).to_be_visible()
    page.get_by_role("button", name="Show more (15 left)").click()
    expect(rows(page)).to_have_count(45)

    # Search by title (case-insensitive) and by quick-summary text.
    search = page.get_by_role("searchbox")
    search.fill("BUDGET")
    expect(rows(page)).to_have_count(9)
    expect(page.get_by_text("9 of 45")).to_be_visible()
    search.fill("rollout item 003")
    expect(rows(page)).to_have_count(1)
    search.fill("no such thing")
    expect(page.get_by_text("No recordings match your search.")).to_be_visible()
    page.get_by_role("button", name="Clear filters").click()
    expect(rows(page)).to_have_count(30)

    # Status filter is a segmented control.
    page.get_by_role("radio", name="Failed").click()
    expect(page.get_by_text("No recordings match your search.")).to_be_visible()
    page.get_by_role("radio", name="All").click()

    # Filter, scroll, open a row, go back.
    search.fill("Weekly")
    expect(page.get_by_text("36 of 45")).to_be_visible()      # the debounced search has applied
    expect(rows(page)).to_have_count(30)
    page.get_by_role("button", name=re.compile("Show more")).click()
    target = page.locator('[data-row-id="seed-037"]')
    target.scroll_into_view_if_needed()
    page.evaluate("window.scrollBy(0, 120)")
    before = page.evaluate("window.scrollY")
    assert before > 600
    target.get_by_role("link", name="Ready. Open Weekly sync 037").click()
    expect(page.get_by_role("heading", name="Weekly sync 037")).to_be_visible()

    page.get_by_role("link", name="Back").click()
    expect(page.get_by_role("searchbox")).to_have_value("Weekly")
    expect(page.locator('[data-row-id="seed-037"]')).to_have_class(re.compile("is-marked"))
    page.wait_for_function("document.activeElement && document.activeElement.closest('[data-row-id]')?.dataset.rowId === 'seed-037'")
    assert abs(page.evaluate("window.scrollY") - before) < 8
    assert rows(page).count() == 36   # 45 minus the 9 'Budget review' ones: same number of loaded rows

    # Browser back works too (and a full reload keeps the filter for this tab).
    page.locator('[data-row-id="seed-037"]').get_by_role("link", name="Ready. Open Weekly sync 037").click()
    expect(page.get_by_role("heading", name="Weekly sync 037")).to_be_visible()
    page.go_back()
    expect(page.get_by_role("searchbox")).to_have_value("Weekly")
    assert abs(page.evaluate("window.scrollY") - before) < 8


def test_settings_modal_tabs_keyboard_and_deep_links(live_server, browser_page, data_dir):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/#settings/about")
    dialog = page.get_by_role("dialog", name="Settings")
    expect(dialog).to_be_visible()
    expect(dialog.get_by_role("tab", name="About")).to_have_attribute("aria-selected", "true")
    expect(dialog.get_by_role("tabpanel", name="About")).to_contain_text("Where your files are")

    # Roving tabindex + arrow keys, Home / End.
    tabs = dialog.get_by_role("tablist")
    about = dialog.get_by_role("tab", name="About")
    about.focus()
    page.keyboard.press("ArrowRight")                      # wraps to General
    expect(dialog.get_by_role("tab", name="General")).to_have_attribute("aria-selected", "true")
    expect(dialog.get_by_role("tab", name="General")).to_be_focused()
    page.keyboard.press("End")
    expect(about).to_have_attribute("aria-selected", "true")
    page.keyboard.press("Home")
    page.keyboard.press("ArrowRight")
    expect(dialog.get_by_role("tab", name="Transcription")).to_have_attribute("aria-selected", "true")
    expect(dialog.get_by_role("tab", name="General")).to_have_attribute("tabindex", "-1")
    expect(dialog.get_by_role("tabpanel", name="Transcription")).to_contain_text("Whisper")
    assert page.evaluate("location.hash") == "#settings/transcription"
    assert tabs.evaluate("el => getComputedStyle(el).overflowX") == "auto"

    # Old section names map onto tabs; Esc closes and focus returns to the gear.
    page.keyboard.press("Escape")
    expect(dialog).to_be_hidden()
    expect(page.get_by_role("button", name="Settings")).to_be_focused()
    page.wait_for_function("location.hash === ''")
    page.goto(live_server + "/#settings/checks")
    expect(page.get_by_role("tab", name="Setup")).to_have_attribute("aria-selected", "true")

    # The gear reopens on the last-used tab; the backdrop closes it.
    page.get_by_role("button", name="Close settings").click()
    page.get_by_role("button", name="Settings").click()
    expect(page.get_by_role("tab", name="Setup")).to_have_attribute("aria-selected", "true")
    page.mouse.click(5, 5)
    expect(dialog).to_be_hidden()


def test_settings_modal_closing_restores_the_meeting_route(live_server, browser_page, data_dir):  # noqa: F811
    seed(data_dir, 2)
    page = browser_page
    page.goto(live_server + "/#/m/seed-000")
    expect(page.get_by_role("heading", name="Budget review 000")).to_be_visible()
    page.get_by_role("button", name="Settings").click()
    expect(page.get_by_role("dialog", name="Settings")).to_be_visible()
    page.keyboard.press("Escape")
    page.wait_for_function("location.hash === '#/m/seed-000'")
    expect(page.get_by_role("heading", name="Budget review 000")).to_be_visible()
