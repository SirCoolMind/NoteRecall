"""Browser check for the optional YouTube link: invisible until Settings turns it on,
then one field on Home that adds a meeting. The download is faked."""

import pytest

from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect
from test_link import fake_fetch  # noqa: F401  (fixture)

pytestmark = pytest.mark.e2e

URL = "https://youtu.be/dQw4w9WgXcQ"


def open_settings(page):
    page.get_by_role("button", name="Settings").click()
    return page.get_by_role("dialog", name="Settings")


def test_link_field_is_hidden_until_turned_on_then_adds_a_meeting(live_server, browser_page, fake_fetch):  # noqa: F811
    page = browser_page
    page.goto(live_server + "/")
    expect(page.get_by_role("button", name="Choose a recording")).to_be_visible()
    expect(page.get_by_role("textbox", name="YouTube link")).to_be_hidden()

    dialog = open_settings(page)
    switch = dialog.get_by_label("Add recordings from a YouTube link")
    expect(switch).not_to_be_checked()
    expect(dialog.get_by_role("button", name="Install the downloader (about 3 MB)")).to_be_hidden()
    switch.check()
    expect(dialog.get_by_role("button", name="Install the downloader (about 3 MB)")).to_be_visible()
    page.keyboard.press("Escape")

    # the field appeared without a reload, and choosing a file is still there
    field = page.get_by_role("textbox", name="YouTube link")
    expect(field).to_be_visible()
    expect(page.get_by_role("button", name="Choose a recording")).to_be_visible()
    add = page.get_by_role("button", name="Add link")
    expect(add).to_be_disabled()

    field.fill("https://example.com/not-youtube")
    add.click()
    expect(page.locator(".note").get_by_text("That does not look like a link to a YouTube video.")).to_be_visible()
    assert fake_fetch.calls == []

    field.fill(URL)
    field.press("Enter")
    expect(page.get_by_role("link", name="Ready. Open Town hall, October")).to_be_visible()
    expect(field).to_have_value("")
    assert fake_fetch.calls == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]

    # still on after a reload; turning it off removes the field again
    page.reload()
    expect(page.get_by_role("textbox", name="YouTube link")).to_be_visible()
    dialog = open_settings(page)
    dialog.get_by_label("Add recordings from a YouTube link").uncheck()
    page.keyboard.press("Escape")
    expect(page.get_by_role("textbox", name="YouTube link")).to_be_hidden()
    expect(page.get_by_role("link", name="Ready. Open Town hall, October")).to_be_visible()   # the meeting stays


def test_link_field_and_errors_in_malay(live_server, browser_page, fake_fetch, client):  # noqa: F811
    import linkfetch

    client.post("/api/config", json={"youtube_links": True})
    fake_fetch.error = linkfetch.LinkError("unavailable", "raw text nobody should see")
    page = browser_page
    page.goto(live_server + "/")
    page.get_by_role("button", name="Bahasa Melayu").click()
    field = page.get_by_role("textbox", name="Pautan YouTube")
    expect(field).to_have_attribute("placeholder", "Atau tampal pautan YouTube")
    field.fill(URL)
    page.get_by_role("button", name="Tambah pautan").click()
    expect(page.get_by_text("YouTube tidak memberikan video ini.", exact=False)).to_be_visible()
    expect(page.get_by_text("raw text nobody should see")).to_have_count(0)
