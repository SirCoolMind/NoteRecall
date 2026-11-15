"""The optional "YouTube links" setting: off by default, a link becomes an ordinary meeting.
The download is always faked here; nothing in these tests reaches the network."""

import pytest

import linkfetch
import server
from conftest import CANNED_SEGMENTS, make_wav_bytes, wait_for

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def meta_of(client, mid):
    return client.get(f"/api/meetings/{mid}").json()["meta"]


class FakeFetch:
    """Stands in for linkfetch.fetch: writes a tiny audio file, or fails with `error`."""

    def __init__(self):
        self.calls = []
        self.error = None
        self.title = "Town hall, October"

    def __call__(self, url, dest_dir, progress=None):
        self.calls.append(url)
        if self.error:
            raise self.error
        if progress:
            progress(0.5)
            progress(1.0)
        (dest_dir / "audio.m4a").write_bytes(make_wav_bytes())
        return {"file": "audio.m4a", "title": self.title, "duration": 0.2}


@pytest.fixture
def fake_fetch(monkeypatch):
    fake = FakeFetch()
    monkeypatch.setattr(linkfetch, "fetch", fake)
    monkeypatch.setattr(linkfetch, "available", lambda: True)
    return fake


@pytest.fixture
def links_on(client):
    assert client.post("/api/config", json={"youtube_links": True}).json()["youtube_links"] is True


def add(client, **body):
    return client.post("/api/meetings/link", json={"url": URL, **body})


# ---------------------------------------------------------------- which links count

@pytest.mark.parametrize("text", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=4&t=30s",
    "http://m.youtube.com/watch?feature=share&v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ?si=abc",
    "youtu.be/dQw4w9WgXcQ",
    "  https://www.youtube.com/shorts/dQw4w9WgXcQ  ",
    "https://www.youtube.com/live/dQw4w9WgXcQ",
    "https://www.youtube.com/embed/dQw4w9WgXcQ",
    "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
])
def test_video_links_become_one_plain_watch_url(text):
    assert linkfetch.video_url(text) == URL


@pytest.mark.parametrize("text", [
    "", "   ", None, 42, "not a link", "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ", "https://www.youtube.com/",
    "https://www.youtube.com/playlist?list=PL123", "https://www.youtube.com/@somechannel",
    "https://www.youtube.com/watch?v=short", "ftp://youtu.be/dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ extra words", "file:///C:/secret.txt",
])
def test_everything_else_is_refused(text):
    assert linkfetch.video_url(text) is None


def test_failure_messages_sort_into_codes():
    assert linkfetch._code_for("ERROR: [youtube] abc: Private video. Sign in if you've been granted access") == "unavailable"
    assert linkfetch._code_for("ERROR: [youtube] abc: Video unavailable") == "unavailable"
    assert linkfetch._code_for("ERROR: [youtube] abc: This video is unavailable") == "unavailable"
    assert linkfetch._code_for("<urlopen error [Errno 11001] getaddrinfo failed>") == "network"
    assert linkfetch._code_for("ERROR: unable to extract player response") == "failed"


# ---------------------------------------------------------------- the setting

def test_off_by_default_and_the_endpoint_refuses(client, fake_fetch):
    assert client.get("/api/config").json()["youtube_links"] is False
    r = add(client)
    assert r.status_code == 403 and r.json()["detail"] == "link_off"
    assert client.get("/api/meetings").json() == []
    assert fake_fetch.calls == []


def test_setting_turns_on_and_off_and_ignores_junk(client):
    assert client.post("/api/config", json={"youtube_links": True}).json()["youtube_links"] is True
    assert client.post("/api/config", json={"youtube_links": "yes"}).json()["youtube_links"] is True
    assert client.post("/api/config", json={"youtube_links": False}).json()["youtube_links"] is False


def test_turning_it_off_again_refuses_new_links(client, links_on, fake_fetch):
    client.post("/api/config", json={"youtube_links": False})
    assert add(client).status_code == 403


def test_bad_link_is_refused_without_creating_a_meeting(client, links_on, fake_fetch):
    r = client.post("/api/meetings/link", json={"url": "https://example.com/video"})
    assert r.status_code == 400 and r.json()["detail"] == "link_bad_link"
    assert client.get("/api/meetings").json() == []


def test_missing_downloader_is_said_plainly(client, links_on, monkeypatch):
    monkeypatch.setattr(linkfetch, "available", lambda: False)
    r = add(client)
    assert r.status_code == 409 and r.json()["detail"] == "link_not_installed"
    assert client.get("/api/meetings").json() == []


def test_uploading_a_file_is_unchanged_by_the_setting(client, links_on, fake_fetch, upload):
    mid = upload("Standup")
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    assert "source_url" not in meta_of(client, mid)
    assert fake_fetch.calls == []


# ---------------------------------------------------------------- a link becomes a meeting

def test_link_downloads_then_runs_like_any_recording(client, links_on, fake_fetch, data_dir):
    mid = add(client, language="ms", num_speakers=3).json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "done")

    body = client.get(f"/api/meetings/{mid}").json()
    meta = body["meta"]
    assert fake_fetch.calls == [URL]
    assert meta["title"] == "Town hall, October"          # the video's own title
    assert meta["source_url"] == URL
    assert meta["audio_file"] == "audio.m4a"
    assert (meta["language"], meta["num_speakers"]) == ("ms", 3)
    assert body["segments"] == CANNED_SEGMENTS
    assert client.get(f"/api/meetings/{mid}/audio").status_code == 200
    assert "error" not in meta and "error_code" not in meta


def test_playlist_and_tracking_parts_are_dropped(client, links_on, fake_fetch):
    r = client.post("/api/meetings/link",
                    json={"url": "https://youtu.be/dQw4w9WgXcQ?list=PL123&si=track"})
    mid = r.json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    assert fake_fetch.calls == [URL]


def test_a_title_you_typed_is_kept(client, links_on, fake_fetch):
    mid = add(client, title="  Budget review  ").json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    assert meta_of(client, mid)["title"] == "Budget review"


def test_rename_while_waiting_is_kept(client, links_on, fake_fetch, fake_pipeline, upload):
    fake_pipeline.pause()
    upload("First")                                # holds the worker
    assert fake_pipeline.reached_pause.wait(timeout=10)
    mid = add(client).json()["id"]                 # queued behind it, nothing downloaded yet
    assert meta_of(client, mid)["title"] == linkfetch.PLACEHOLDER_TITLE
    assert client.get(f"/api/meetings/{mid}/audio").status_code == 404
    client.patch(f"/api/meetings/{mid}", json={"title": "My own name"})
    fake_pipeline.resume()
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    assert meta_of(client, mid)["title"] == "My own name"


def test_download_progress_stays_under_the_first_pipeline_stage(client, links_on, fake_fetch, monkeypatch):
    seen = []
    real = fake_fetch.__call__

    def watching(url, dest_dir, progress=None):
        out = real(url, dest_dir, progress)
        seen.append(dict(server.live_status[dest_dir.name]))
        return out

    monkeypatch.setattr(linkfetch, "fetch", watching)
    mid = add(client).json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    assert seen == [{"stage": "downloading", "progress": server.DOWNLOAD_SHARE}]
    assert server.DOWNLOAD_SHARE < 5


@pytest.mark.parametrize("code", ["unavailable", "live", "too_long", "network", "failed"])
def test_failed_download_is_a_failed_meeting_with_a_code(client, links_on, fake_fetch, code):
    fake_fetch.error = linkfetch.LinkError(code, "raw downloader text")
    mid = add(client).json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "error")
    meta = meta_of(client, mid)
    assert meta["error_code"] == "link_" + code
    assert meta["error"] == "raw downloader text"
    assert client.get(f"/api/meetings/{mid}/audio").status_code == 404


def test_try_again_downloads_again_and_clears_the_error(client, links_on, fake_fetch):
    fake_fetch.error = linkfetch.LinkError("network")
    mid = add(client).json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "error")

    fake_fetch.error = None
    assert client.post(f"/api/meetings/{mid}/retranscribe").status_code == 200
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    meta = meta_of(client, mid)
    assert fake_fetch.calls == [URL, URL]
    assert "error" not in meta and "error_code" not in meta
    assert meta["title"] == "Town hall, October"


def test_transcribing_again_does_not_download_again(client, links_on, fake_fetch):
    mid = add(client).json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "done")
    client.post(f"/api/meetings/{mid}/retranscribe")
    server.jobs.join()
    assert meta_of(client, mid)["status"] == "done"
    assert fake_fetch.calls == [URL]


def test_a_pipeline_error_after_a_good_download_has_no_link_code(client, links_on, fake_fetch, monkeypatch):
    import pipeline

    def boom(*a, **k):
        raise RuntimeError("decoder fell over")

    monkeypatch.setattr(pipeline, "run_job", boom)
    mid = add(client).json()["id"]
    wait_for(lambda: meta_of(client, mid)["status"] == "error")
    meta = meta_of(client, mid)
    assert meta["error"] == "decoder fell over" and "error_code" not in meta


# ---------------------------------------------------------------- the downloader is an optional install

def test_downloader_is_an_optional_check_with_an_install_step(client):
    import config
    import installer

    check = next(c for c in server._evaluate(config.load())["checks"] if c["id"] == "yt_dlp")
    assert check["req"] == "optional" and check["auto"] is True
    assert check["fix"]["windows"] and check["fix"]["linux"]
    assert "yt_dlp" in installer.default_steps()


def test_install_step_upgrades_so_it_is_also_the_fix(monkeypatch):
    import installer

    ran = []
    monkeypatch.setattr(installer, "_pip_install", lambda args, report: ran.append(args))
    installer.step_yt_dlp(lambda *a: None)
    assert ran == [["--upgrade", "yt-dlp"]]


def test_downloader_is_not_a_requirement_for_everyone():
    text = (server.BASE_DIR / "requirements.txt").read_text(encoding="utf-8").lower()
    assert "yt-dlp" not in text and "yt_dlp" not in text
