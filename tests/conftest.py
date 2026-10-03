"""Shared fixtures: temp data dir, TestClient and a controllable fake pipeline.

Nothing here touches the real data/ folder or config.json.
"""

import io
import threading
import time
import wave

import pytest
from fastapi.testclient import TestClient

import config
import pipeline
import server
import summarizer

CANNED_SEGMENTS = [
    {"start": 0.0, "end": 2.0, "speaker": 0, "text": "Selamat pagi semua."},
    {"start": 2.0, "end": 4.5, "speaker": 1, "text": "Good morning, let us begin."},
]


def make_wav_bytes(seconds: float = 0.2, rate: int = 8000) -> bytes:
    """A tiny silent mono WAV generated in memory."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


class FakePipeline:
    """Replaces pipeline.run_job. Emits staged progress; the test can hold the
    job mid-processing with pause() and release it with resume()."""

    def __init__(self):
        self.gate = threading.Event()
        self.gate.set()
        self.reached_pause = threading.Event()  # set once a job is parked at the gate

    def pause(self):
        self.reached_pause.clear()
        self.gate.clear()

    def resume(self):
        self.gate.set()

    def _checkpoint(self):
        if not self.gate.is_set():
            self.reached_pause.set()
            assert self.gate.wait(timeout=10), "fake pipeline was never resumed"

    def run_job(self, audio_path, work_dir, language, num_speakers, status_cb):
        status_cb("converting", 5)
        status_cb("transcribing", 30)
        self._checkpoint()
        status_cb("transcribing", 60)
        status_cb("diarizing", 80)
        status_cb("summarizing", 95)
        return {"segments": [dict(s) for s in CANNED_SEGMENTS], "language": "ms",
                "duration": 4.5, "num_speakers": 2}

    def rediarize_job(self, audio_path, work_dir, segments, num_speakers, status_cb):
        status_cb("diarizing", 50)
        self._checkpoint()
        return {"segments": segments, "num_speakers": num_speakers or 2}


@pytest.fixture
def fake_pipeline(monkeypatch):
    fake = FakePipeline()
    monkeypatch.setattr(pipeline, "run_job", fake.run_job)
    monkeypatch.setattr(pipeline, "rediarize_job", fake.rediarize_job)
    monkeypatch.setattr(summarizer, "summarize",
                        lambda segments, names: ("Fake summary", "fake"))
    yield fake
    fake.resume()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(server, "DATA_DIR", d)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    return d


@pytest.fixture
def client(data_dir, fake_pipeline):
    # Not used as a context manager, so the app lifespan (which would requeue
    # jobs from the data dir) does not run. Start one shared worker thread
    # instead; it reads DATA_DIR and pipeline.* lazily so monkeypatching works.
    if not server._worker_started:
        server._worker_started = True
        threading.Thread(target=server.worker, daemon=True).start()
    yield TestClient(server.app)
    fake_pipeline.resume()
    server.jobs.join()


@pytest.fixture
def upload(client):
    def _upload(title="", **form):
        r = client.post(
            "/api/meetings",
            files={"file": ("standup.wav", make_wav_bytes(), "audio/wav")},
            data={"title": title, **form})
        assert r.status_code == 200
        return r.json()["id"]
    return _upload


def wait_for(predicate, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not reached in time")
