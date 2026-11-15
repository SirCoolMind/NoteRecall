"""Browser checks for listening: playback speed, back 5 seconds, and keys that work anywhere on a
meeting page. Uses a seeded meeting with a short generated recording; no pipeline runs."""

import pytest

from conftest import make_wav_bytes
from test_corrections import seed
from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect

pytestmark = pytest.mark.e2e

AUDIO = "document.querySelector('.ribbon audio')"


@pytest.fixture
def meeting(data_dir):
    mid = seed(data_dir)
    (data_dir / mid / "audio.wav").write_bytes(make_wav_bytes(seconds=9))
    return mid


def ready(page, live_server, mid):
    page.goto(f"{live_server}/#/m/{mid}")
    expect(page.get_by_role("button", name="Play", exact=True)).to_be_visible()
    page.wait_for_function(f"{AUDIO}.readyState >= 1")


def test_which_key_means_what(live_server, browser_page):  # noqa: F811
    page = browser_page
    page.goto(live_server)
    got = page.evaluate("""async () => {
      const k = await import('/static/js/keys.js');
      const free = { typing: false, ownKeys: false, pressable: false };
      const key = (key, where = free, mods = {}) => k.shortcutFor({ key, ...mods }, where);
      return {
        space: key(' '), k: key('k'), left: key('ArrowLeft'), right: key('ArrowRight'),
        slower: key('['), faster: key(']'), find: key('/'), help: key('?'), other: key('a'),
        typing: key(' ', { ...free, typing: true }),
        inMenu: key('ArrowLeft', { ...free, ownKeys: true }),
        spaceOnButton: key(' ', { ...free, pressable: true }),
        arrowOnButton: key('ArrowLeft', { ...free, pressable: true }),
        withCtrl: key('k', free, { ctrlKey: true }),
        up: [1, 1.25, 2].map((s) => k.stepSpeed(s, 1)),
        down: [1, 0.75].map((s) => k.stepSpeed(s, -1)),
        cycle: [1, 2, 0.75].map((s) => k.cycleSpeed(s)),
        label: k.speedLabel(1.25),
      };
    }""")
    assert got == {
        "space": "toggle", "k": "toggle", "left": "back", "right": "forward",
        "slower": "slower", "faster": "faster", "find": "find", "help": "help", "other": None,
        "typing": None, "inMenu": None, "spaceOnButton": None, "arrowOnButton": "back", "withCtrl": None,
        "up": [1.25, 1.5, 2], "down": [0.75, 0.75], "cycle": [1.25, 0.75, 1], "label": "1.25×",
    }


def test_speed_is_applied_and_remembered(live_server, browser_page, meeting):  # noqa: F811
    page = browser_page
    ready(page, live_server, meeting)
    speed = page.get_by_role("button", name="Playback speed 1×. Press to change.")
    speed.click()
    expect(page.get_by_role("button", name="Playback speed 1.25×. Press to change.")).to_be_visible()
    assert page.evaluate(f"{AUDIO}.playbackRate") == 1.25

    page.locator("body").press("]")
    assert page.evaluate(f"{AUDIO}.playbackRate") == 1.5
    page.locator("body").press("[")
    page.locator("body").press("[")
    assert page.evaluate(f"{AUDIO}.playbackRate") == 1

    page.locator("body").press("]")
    page.reload()
    page.wait_for_function(f"{AUDIO} && {AUDIO}.readyState >= 1")
    expect(page.get_by_role("button", name="Playback speed 1.25×. Press to change.")).to_be_visible()
    assert page.evaluate(f"{AUDIO}.playbackRate") == 1.25


def test_keys_work_anywhere_but_not_while_typing(live_server, browser_page, meeting):  # noqa: F811
    page = browser_page
    ready(page, live_server, meeting)
    body = page.locator("body")

    body.press("ArrowRight")
    assert page.evaluate(f"{AUDIO}.currentTime") == 5
    page.get_by_role("button", name="Back 5 seconds").click()
    assert page.evaluate(f"{AUDIO}.currentTime") == 0
    body.press("ArrowRight")
    body.press("ArrowLeft")
    assert page.evaluate(f"{AUDIO}.currentTime") == 0

    # Space on a focused button presses that button, as everywhere else; from the page it plays
    page.evaluate("document.activeElement.blur()")
    body.press("Space")
    expect(page.get_by_role("button", name="Pause", exact=True)).to_be_visible()
    body.press("k")
    expect(page.get_by_role("button", name="Play", exact=True)).to_be_visible()

    # '/' goes to the transcript search; typing there never drives the player
    body.press("/")
    find = page.get_by_role("searchbox", name="Search the transcript")
    expect(find).to_be_focused()
    find.press_sequentially("k ]")
    expect(find).to_have_value("k ]")
    expect(page.get_by_role("button", name="Play", exact=True)).to_be_visible()
    assert page.evaluate(f"{AUDIO}.playbackRate") == 1

    # the editor of a line is typing too
    find.fill("")
    page.get_by_role("button", name="Correct the line at 0:04").click()
    page.get_by_role("menuitem", name="Edit text").click()
    box = page.get_by_label("Text of the line at 0:04")
    box.press("ArrowRight")
    box.press_sequentially(" k")
    assert page.evaluate(f"{AUDIO}.currentTime") == 0
    expect(page.get_by_role("button", name="Play", exact=True)).to_be_visible()


def test_shortcut_list_opens_with_question_mark_and_reads_in_malay(live_server, browser_page, meeting):  # noqa: F811
    page = browser_page
    ready(page, live_server, meeting)
    page.locator("body").press("?")
    expect(page.get_by_role("heading", name="Keyboard shortcuts")).to_be_visible()
    expect(page.get_by_text("Back or forward 5 seconds")).to_be_visible()
    # keys stay with the dialog while it is open
    page.keyboard.press("ArrowRight")
    assert page.evaluate(f"{AUDIO}.currentTime") == 0
    page.get_by_role("button", name="Close").click()

    page.get_by_role("button", name="Bahasa Melayu").click()
    expect(page.get_by_role("button", name="Undur 5 saat")).to_be_visible()
    page.get_by_role("button", name="Tindakan lain").click()
    page.get_by_role("menuitem", name="Pintasan papan kekunci").click()
    expect(page.get_by_text("Main atau jeda")).to_be_visible()
