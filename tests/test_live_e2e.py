"""Browser check for reading while it works: lines appear on the waiting page during processing,
the browser tab shows the percentage, and the finished transcript takes over."""

import pytest

from conftest import make_wav_bytes
from test_e2e import browser_page, live_server  # noqa: F401  (fixtures)
from test_e2e import expect

pytestmark = pytest.mark.e2e


def test_tab_title_parts(live_server, browser_page):  # noqa: F811
    page = browser_page
    page.goto(live_server)
    got = page.evaluate("""async () => {
      const { tabTitle } = await import('/static/js/tabtitle.js');
      return [tabTitle(), tabTitle({ name: 'Ops' }), tabTitle({ name: 'Ops', progress: 61.6 }),
              tabTitle({ progress: 0 }), tabTitle({ name: 'Ops', mark: '✓' })];
    }""")
    assert got == ["NoteRecall", "Ops · NoteRecall", "62% · Ops · NoteRecall", "0% · NoteRecall", "✓ · Ops · NoteRecall"]


def test_read_the_transcript_while_it_is_processed(live_server, browser_page, fake_pipeline, tmp_path):  # noqa: F811
    page = browser_page
    audio = tmp_path / "standup.wav"
    audio.write_bytes(make_wav_bytes(seconds=3))
    page.goto(live_server + "/")

    fake_pipeline.pause()
    page.get_by_label("Choose a recording").set_input_files(str(audio))
    assert fake_pipeline.reached_pause.wait(timeout=10), "job never started processing"
    expect(page).to_have_title("30% · NoteRecall")

    page.get_by_role("link", name="Read standup as it is transcribed").click()
    expect(page.get_by_role("heading", name="Transcribed so far")).to_be_visible()
    expect(page.get_by_text("1 line", exact=True)).to_be_visible()
    expect(page.get_by_text("Selamat pagi semua.")).to_be_visible()
    expect(page.get_by_text("Good morning, let us begin.")).to_have_count(0)
    expect(page).to_have_title("30% · standup · NoteRecall")

    page.get_by_role("button", name="Bahasa Melayu").click()
    expect(page.get_by_role("heading", name="Ditranskripsi setakat ini")).to_be_visible()
    page.get_by_role("button", name="English").click()

    fake_pipeline.resume()
    expect(page.get_by_role("tabpanel", name="Transcript").get_by_text("Good morning, let us begin.")).to_be_visible()
    expect(page.get_by_role("heading", name="Transcribed so far")).to_have_count(0)
    expect(page).to_have_title("standup · NoteRecall")

    page.get_by_role("link", name="Back to schedule").click()
    expect(page).to_have_title("NoteRecall")
