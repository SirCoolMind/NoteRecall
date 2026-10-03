"""Browser end-to-end flow: drop -> process -> rename -> Ready -> download, then BM/EN.

Runs the real FastAPI app under uvicorn on a free port, with the fake pipeline
and a temp data dir/config. Skips cleanly when Playwright's Chromium is missing.
Only accessible role/label/text queries are used.
"""

import socket
import threading

import pytest

import server
from conftest import CANNED_SEGMENTS, make_wav_bytes

pytestmark = pytest.mark.e2e

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect


@pytest.fixture
def live_server(client, monkeypatch):
    """The real app on a free port. `client` brings the temp data dir, temp
    config, fake pipeline and a running worker thread."""
    import uvicorn

    ready = {"checks": [{"id": "python", "name": "Python", "ok": True, "detail": "",
                         "hint": "", "req": "always", "auto": False,
                         "fix": {"windows": [], "linux": []}}],
             "engine": "local", "os": "linux", "os_detail": "test", "compute": "cpu"}
    monkeypatch.setattr(server, "_evaluate", lambda cfg: dict(ready))

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(server.app, log_level="warning"))
    thread = threading.Thread(target=srv.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not srv.started:
        assert thread.is_alive(), "uvicorn failed to start"
        threading.Event().wait(0.02)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.fixture
def browser_page():
    try:
        pw = sync_api.sync_playwright().start()
    except Exception as e:  # pragma: no cover
        pytest.skip(f"Playwright unavailable: {e}")
    try:
        browser = pw.chromium.launch()
    except Exception as e:
        pw.stop()
        pytest.skip(f"Chromium not installed (python -m playwright install chromium): {e}")
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    page.set_default_timeout(10_000)
    expect.set_options(timeout=10_000)
    yield page
    context.close()
    browser.close()
    pw.stop()


def test_drop_wait_download_in_both_languages(live_server, browser_page, fake_pipeline, data_dir, tmp_path):
    page = browser_page
    audio = tmp_path / "standup.wav"
    audio.write_bytes(make_wav_bytes(seconds=3))

    page.goto(live_server + "/")
    expect(page.get_by_role("heading", name="Next recording")).to_be_visible()
    expect(page.get_by_role("button", name="Choose a recording")).to_be_enabled()

    # Drop a recording and park the fake mid-processing.
    fake_pipeline.pause()
    page.get_by_label("Choose a recording").set_input_files(str(audio))
    assert fake_pipeline.reached_pause.wait(timeout=10), "job never started processing"
    expect(page.get_by_text("Processing", exact=True)).to_be_visible()

    # Rename the title inline while it is processing.
    page.get_by_role("button", name="Edit title: standup").click()
    box = page.get_by_label("Meeting title")
    box.fill("Weekly sync")
    box.press("Enter")
    expect(page.get_by_text("Weekly sync", exact=True)).to_be_visible()

    # Let it finish, open it.
    fake_pipeline.resume()
    page.get_by_role("link", name="Ready. Open Weekly sync").click()
    expect(page.get_by_text("Good morning, let us begin.")).to_be_visible()
    expect(page.get_by_role("heading", name="Weekly sync")).to_be_visible()

    # Download plate (txt).
    with page.expect_download() as dl_info:
        page.get_by_role("link", name="Download .txt").click()
    download = dl_info.value
    assert download.suggested_filename == "Weekly sync.txt"
    text = open(download.path(), encoding="utf-8").read()
    assert text.startswith("Weekly sync")
    for seg in CANNED_SEGMENTS:
        assert seg["text"] in text

    # The title persisted through the API too.
    meetings = page.request.get(live_server + "/api/meetings").json()
    assert [m["title"] for m in meetings] == ["Weekly sync"]

    # BM/EN toggle changes visible labels.
    page.get_by_role("button", name="Bahasa Melayu").click()
    expect(page.get_by_role("link", name="Muat turun .txt")).to_be_visible()
    page.get_by_role("button", name="English").click()
    expect(page.get_by_role("link", name="Download .txt")).to_be_visible()
