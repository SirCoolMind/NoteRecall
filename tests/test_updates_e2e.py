"""Browser checks for versioning and the updater UI. The check/apply endpoints are faked on the
server's Updater (no git, no network); the app runs on a temp data dir like the other e2e tests."""

import re

import pytest

import server
from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect

pytestmark = pytest.mark.e2e

NOTES = "Faster transcripts.\nSecond line <b>not bold</b>\n\n- one\n- two"


def result(available=True, **extra):
    base = {"current": "0.1.0", "latest": "0.2.0" if available else "0.1.0", "available": available,
            "notes": NOTES if available else "", "url": "https://github.com/SirCoolMind/NoteRecall/releases/tag/v0.2.0",
            "checked_at": 1790000000}
    return {**base, **extra}


@pytest.fixture
def fake_updater(monkeypatch):
    state = {"check": result(), "calls": 0, "can_update": True, "reason": "", "reason_code": "", "install_type": "git",
             "apply": None, "status": {"state": "idle", "running": False, "steps": [], "target": None, "message": ""}}
    u = server.app_updater

    def check(force=False):
        state["calls"] += 1
        return state["check"]

    monkeypatch.setattr(u, "check", check)
    monkeypatch.setattr(u, "version_info", lambda: {
        "version": "0.1.0", "install_type": state["install_type"], "can_update": state["can_update"],
        "reason": state["reason"], "reason_code": state["reason_code"]})
    monkeypatch.setattr(u, "status", lambda: state["status"])

    def apply():
        state["status"] = state["apply"]
        return state["status"]

    monkeypatch.setattr(u, "apply", apply)
    return state


def test_about_shows_the_version(live_server, browser_page, fake_updater):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/#settings/about")
    expect(page.get_by_text("Version 0.1.0", exact=True)).to_be_visible()
    assert page.request.get(live_server + "/api/status").json()["version"] == "0.1.0"


def test_masthead_indicator_opens_updates_with_notes(live_server, browser_page, fake_updater):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    chip = page.get_by_role("link", name="Update available: version 0.2.0")
    expect(chip).to_be_visible()
    box = chip.bounding_box()
    assert box["height"] >= 44
    chip.click()
    expect(page).to_have_url(re.compile(r"#settings/updates$"))
    expect(page.get_by_role("tab", name="Updates")).to_have_attribute("aria-selected", "true")
    panel = page.get_by_role("tabpanel", name="Updates")
    expect(panel.get_by_text("0.1.0", exact=True)).to_be_visible()
    expect(panel.get_by_text("Installed with Git")).to_be_visible()
    expect(panel.get_by_text("Your meetings, settings and downloaded models are kept.")).to_be_visible()
    expect(panel.get_by_role("heading", name="Version 0.2.0 is available")).to_be_visible()
    notes = panel.locator(".upd__notes")
    expect(notes).to_contain_text("Second line <b>not bold</b>")      # shown as text, never parsed as HTML
    assert page.locator(".upd__notes b").count() == 0
    assert "\n" in notes.inner_text()
    expect(panel.get_by_role("button", name="Update now")).to_be_enabled()


def test_no_indicator_when_up_to_date_and_check_button_says_so(live_server, browser_page, fake_updater):  # noqa: F811
    fake_updater["check"] = result(available=False)
    page = browser_page
    page.goto(live_server + "/#settings/updates")
    expect(page.get_by_role("link", name=re.compile("Update available"))).to_have_count(0)
    panel = page.get_by_role("tabpanel", name="Updates")
    page.get_by_role("button", name="Check for updates").click()
    expect(panel.get_by_text("You're up to date")).to_be_visible()
    expect(panel.get_by_role("button", name="Update now")).to_be_hidden()


def test_automatic_check_runs_at_most_once_a_day(live_server, browser_page, fake_updater):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    expect(page.get_by_role("link", name="Update available: version 0.2.0")).to_be_visible()
    assert fake_updater["calls"] == 1
    page.reload()
    page.wait_for_timeout(800)
    expect(page.get_by_role("link", name="Update available: version 0.2.0")).to_be_visible()   # remembered, not re-asked
    assert fake_updater["calls"] == 1


def test_offline_is_a_friendly_message_not_an_error_page(live_server, browser_page, fake_updater):  # noqa: F811
    fake_updater["check"] = result(available=False, latest=None, error="network", message="Couldn't reach GitHub.")
    page = browser_page
    page.goto(live_server + "/#settings/updates")
    page.get_by_role("button", name="Check for updates").click()
    expect(page.get_by_text("Couldn't reach GitHub. Check your internet connection and try again.")).to_be_visible()


def test_refusal_reason_is_shown_and_the_button_is_disabled(live_server, browser_page, fake_updater):  # noqa: F811
    fake_updater.update(can_update=False, reason_code="busy",
                        reason="NoteRecall is still working on a meeting. Wait until it finishes, then update.")
    page = browser_page
    page.goto(live_server + "/#settings/updates")
    panel = page.get_by_role("tabpanel", name="Updates")
    page.get_by_role("button", name="Check for updates").click()
    expect(panel.get_by_role("button", name="Update now")).to_be_disabled()
    expect(panel.get_by_text("still working on a meeting")).to_be_visible()


def test_malay_labels(live_server, browser_page, fake_updater):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    page.get_by_role("button", name=re.compile("Bahasa Melayu")).click()
    expect(page.get_by_role("link", name="Kemas kini tersedia: versi 0.2.0")).to_be_visible()
    page.get_by_role("link", name="Kemas kini tersedia: versi 0.2.0").click()
    expect(page.get_by_role("tab", name="Kemas kini")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("heading", name="Versi 0.2.0 tersedia")).to_be_visible()


def test_apply_shows_steps_then_reloads_into_the_new_version(live_server, browser_page, fake_updater, monkeypatch):  # noqa: F811
    steps = [{"id": "code", "state": "done", "message": ""}, {"id": "packages", "state": "done", "message": ""},
             {"id": "restart", "state": "running", "message": ""}]
    fake_updater["apply"] = {"state": "restarting", "running": True, "target": "0.2.0", "message": "", "steps": steps}
    page = browser_page
    page.goto(live_server + "/#settings/updates")
    page.get_by_role("button", name="Check for updates").click()
    page.get_by_role("button", name="Update now").click()
    panel = page.get_by_role("tabpanel", name="Updates")
    expect(panel.locator(".upd__restart")).to_contain_text("Restarting NoteRecall…")
    expect(panel.get_by_text("Get the new version")).to_be_visible()
    # The server "comes back" as the new version: the page notices and reloads itself.
    monkeypatch.setattr(server, "__version__", "0.2.0")
    fake_updater["status"] = {"state": "idle", "running": False, "steps": [], "target": None, "message": ""}
    expect(page.get_by_text("Updated to version 0.2.0.")).to_be_visible(timeout=15_000)


def test_failed_update_shows_the_reason(live_server, browser_page, fake_updater):  # noqa: F811
    steps = [{"id": "code", "state": "done", "message": ""},
             {"id": "packages", "state": "failed", "message": "The new files are in place, but installing packages failed: x"},
             {"id": "restart", "state": "pending", "message": ""}]
    fake_updater["apply"] = {"state": "failed", "running": False, "target": "0.2.0", "message": "m", "steps": steps}
    page = browser_page
    page.goto(live_server + "/#settings/updates")
    page.get_by_role("button", name="Check for updates").click()
    page.get_by_role("button", name="Update now").click()
    panel = page.get_by_role("tabpanel", name="Updates")
    expect(panel.get_by_text("installing packages failed")).to_be_visible(timeout=10_000)
    expect(panel.locator(".upd__run .upd__reason")).to_contain_text("The update didn't finish.")
