"""Browser checks for correcting a transcript: edit a line, move it to another speaker, merge two
speakers, delete a line, then discard everything. Uses a seeded meeting; no pipeline runs."""

import json

import pytest

from conftest import make_wav_bytes
from test_corrections import FOUR, seed
from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect

pytestmark = pytest.mark.e2e


@pytest.fixture
def meeting(data_dir):
    mid = seed(data_dir)
    (data_dir / mid / "audio.wav").write_bytes(make_wav_bytes(seconds=9))
    return mid


def lines(page):
    """The transcript panel: the built-in summary repeats sentences, so text is looked up in here."""
    return page.get_by_role("tabpanel", name="Transcript")


def stored(data_dir, mid):
    return json.loads((data_dir / mid / "transcript.json").read_text(encoding="utf-8"))


def test_edit_a_line_in_place(live_server, browser_page, data_dir, meeting):  # noqa: F811
    page = browser_page
    page.goto(f"{live_server}/#/m/{meeting}")
    expect(lines(page).get_by_text("Good morning.", exact=True)).to_be_visible()

    page.get_by_role("button", name="Correct the line at 0:04").click()
    page.get_by_role("menuitem", name="Edit text").click()
    box = page.get_by_label("Text of the line at 0:04")
    expect(box).to_be_focused()
    box.fill("Good morning, everyone.")
    box.press("Enter")

    expect(lines(page).get_by_text("Good morning, everyone.", exact=True)).to_be_visible()
    expect(page.locator(".line.is-edited")).to_have_count(1)
    assert stored(data_dir, meeting)[2]["orig"] == "Good morning."

    # Esc leaves the text alone
    page.get_by_role("button", name="Correct the line at 0:00").click()
    page.get_by_role("menuitem", name="Edit text").click()
    box = page.get_by_label("Text of the line at 0:00")
    box.fill("Something else")
    box.press("Escape")
    expect(lines(page).get_by_text("Selamat pagi semua.", exact=True)).to_be_visible()

    # the menu offers the original back
    page.get_by_role("button", name="Correct the line at 0:04").click()
    page.get_by_role("menuitem", name="Restore the original text").click()
    expect(lines(page).get_by_text("Good morning.", exact=True)).to_be_visible()
    expect(page.locator(".line.is-edited")).to_have_count(0)


def test_move_a_turn_and_delete_a_line(live_server, browser_page, data_dir, meeting):  # noqa: F811
    page = browser_page
    page.goto(f"{live_server}/#/m/{meeting}")
    expect(page.get_by_role("button", name="Speakers · 3")).to_be_visible()

    # the first two lines are one turn by Speaker 1: give the whole turn to Speaker 2
    page.get_by_role("button", name="Correct the line at 0:02").click()
    page.get_by_label("Apply to the whole turn (2 lines)").check()
    page.get_by_role("menuitemradio", name="Speaker 2").click()
    expect(page.get_by_role("button", name="Speakers · 2")).to_be_visible()
    assert [s["speaker"] for s in stored(data_dir, meeting)] == [1, 1, 1, 2]

    # deleting takes two presses of the same item
    page.get_by_role("button", name="Correct the line at 0:06").click()
    page.get_by_role("menuitem", name="Delete this line").click()
    page.get_by_role("menuitem", name="Press again to delete").click()
    expect(lines(page).get_by_text("Morning, sorry lambat.")).to_have_count(0)
    assert len(stored(data_dir, meeting)) == 3


def test_merge_speakers_then_discard_everything(live_server, browser_page, data_dir, meeting):  # noqa: F811
    page = browser_page
    page.goto(f"{live_server}/#/m/{meeting}")
    page.get_by_role("button", name="Speakers · 3").click()
    page.get_by_role("button", name="Merge Speaker 3 into another speaker").click()
    expect(page.get_by_text("Merge Speaker 3 into which speaker?")).to_be_visible()
    page.get_by_role("button", name="Merge into Speaker 1").click()
    expect(page.get_by_text("Merge Speaker 3 into Speaker 1? 1 line will move.")).to_be_visible()
    page.get_by_role("button", name="Merge", exact=True).click()
    expect(page.get_by_role("button", name="Speakers · 2")).to_be_visible()
    assert [s["speaker"] for s in stored(data_dir, meeting)] == [0, 0, 1, 0]

    page.keyboard.press("Escape")
    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Discard my corrections").click()
    page.get_by_role("button", name="Discard corrections").click()
    expect(page.get_by_role("button", name="Speakers · 3")).to_be_visible()
    assert stored(data_dir, meeting) == FOUR
    page.get_by_role("button", name="More actions").click()
    expect(page.get_by_role("menuitem", name="Discard my corrections")).to_be_hidden()


def test_retranscribe_asks_first_when_there_are_corrections(live_server, browser_page, data_dir, meeting, fake_pipeline):  # noqa: F811
    page = browser_page
    page.goto(f"{live_server}/#/m/{meeting}")
    page.get_by_role("button", name="Correct the line at 0:04").click()
    page.get_by_role("menuitem", name="Edit text").click()
    page.get_by_label("Text of the line at 0:04").fill("Changed.")
    page.get_by_role("button", name="Save").click()
    expect(lines(page).get_by_text("Changed.", exact=True)).to_be_visible()

    page.get_by_role("button", name="More actions").click()
    page.get_by_role("menuitem", name="Re-transcribe").click()
    expect(page.get_by_text("Your corrections to this transcript will be lost.")).to_be_visible()
    page.get_by_role("button", name="Cancel").click()
    assert stored(data_dir, meeting)[2]["text"] == "Changed."


def test_corrections_read_in_malay(live_server, browser_page, meeting):  # noqa: F811
    page = browser_page
    page.goto(f"{live_server}/#/m/{meeting}")
    page.get_by_role("button", name="Bahasa Melayu").click()
    page.get_by_role("button", name="Betulkan baris pada 0:04").click()
    expect(page.get_by_role("menuitem", name="Sunting teks")).to_be_visible()
    expect(page.get_by_role("menuitem", name="Padam baris ini")).to_be_visible()
    expect(page.get_by_role("menuitemradio", name="Penutur 2")).to_have_attribute("aria-checked", "true")
    expect(page.get_by_role("menuitem", name="Penutur baharu")).to_be_visible()
