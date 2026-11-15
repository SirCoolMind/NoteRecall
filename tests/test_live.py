"""Read while it works: the lines transcribed so far are served while the job runs, kept in
memory only, and gone once the job has finished."""

import numpy as np

import pipeline
from conftest import CANNED_SEGMENTS, wait_for


def live(client, mid, after=0):
    return client.get(f"/api/meetings/{mid}/live", params={"after": after}).json()


def test_lines_arrive_while_the_job_runs(client, fake_pipeline, upload, data_dir):
    fake_pipeline.pause()
    mid = upload("Standup")
    assert fake_pipeline.reached_pause.wait(timeout=10)

    got = live(client, mid)
    assert got["status"] == "transcribing" and 0 < got["progress"] < 100
    assert got["total"] == 1
    assert got["lines"] == [{"start": 0.0, "text": CANNED_SEGMENTS[0]["text"]}]
    # nothing half-done reaches the disk
    assert not (data_dir / mid / "transcript.json").exists()
    assert client.get(f"/api/meetings/{mid}").json()["segments"] == []

    fake_pipeline.resume()
    wait_for(lambda: live(client, mid)["status"] == "done")
    # finished: the real transcript has taken over
    assert live(client, mid) == {"status": "done", "progress": 100, "total": 0, "lines": []}
    assert client.get(f"/api/meetings/{mid}").json()["segments"] == CANNED_SEGMENTS


def test_after_returns_only_newer_lines(client, fake_pipeline, upload):
    fake_pipeline.pause()
    mid = upload("Standup")
    assert fake_pipeline.reached_pause.wait(timeout=10)
    assert live(client, mid, after=1) == {"status": "transcribing", "progress": 30, "total": 1, "lines": []}
    assert len(live(client, mid, after=-5)["lines"]) == 1
    assert live(client, mid, after=99)["lines"] == []


def test_live_is_404_for_an_unknown_meeting(client):
    assert client.get("/api/meetings/nope/live").status_code == 404


def test_transcribe_hands_over_each_line_as_it_is_produced(monkeypatch):
    class Seg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class Info:
        duration, language = 10.0, "ms"

    class Model:
        def transcribe(self, audio, **kw):
            return iter([Seg(0, 2, " Selamat pagi. "), Seg(2, 3, "   "), Seg(3, 5, "Okay.")]), Info()

    monkeypatch.setattr(pipeline, "get_whisper", lambda: (Model(), "cpu"))
    seen, progress = [], []
    out, lang, duration = pipeline.transcribe(np.zeros(16000, dtype=np.float32), None,
                                              progress.append, lambda s: seen.append(dict(s)))
    assert [s["text"] for s in seen] == ["Selamat pagi.", "Okay."]   # blank lines are never shown
    assert seen == out and lang == "ms" and duration == 10.0
    assert progress == [0.2, 0.5]


def test_run_job_works_with_a_plain_status_callback(monkeypatch, tmp_path):
    """Other callers (and older code) pass a bare function: no .line on it, no live lines, no error."""
    monkeypatch.setattr(pipeline, "convert_to_wav", lambda src, dst: dst.write_bytes(b""))
    monkeypatch.setattr(pipeline, "load_wav", lambda p: np.zeros(16000, dtype=np.float32))
    got = {}

    def fake_transcribe(audio, language, progress_cb=None, line_cb=None):
        got["line_cb"] = line_cb
        return [], "ms", 1.0

    monkeypatch.setattr(pipeline, "transcribe", fake_transcribe)
    monkeypatch.setattr(pipeline, "diarize_labeled", lambda *a, **k: ([], "standard"))
    import config
    monkeypatch.setattr(config, "load", lambda: {"engine": "local"})
    pipeline.run_job(tmp_path / "a.wav", tmp_path, None, None, lambda stage, p: None)
    assert got["line_cb"] is None
