"""Optional Nemotron-3 speaker detection: the soft gate, choosing the diarizer,
the fallbacks to the standard one, and what reaches the meeting. Every model is
a fake: nothing here imports NeMo or PyTorch, or downloads anything."""

import numpy as np
import pytest

import config
import nemo_diar
import pipeline
import server
from conftest import wait_for

STANDARD_TURNS = [(0.0, 2.0, 0), (2.0, 4.5, 1)]
NEMO_TURNS = [(0.0, 4.5, 0)]
AUDIO = np.zeros(1600, dtype=np.float32)


# ---------------------------------------------------------------- soft gate

@pytest.mark.parametrize("count, vram, os_name, driver, reasons", [
    (1, 6141, "windows", 610, []),
    (0, None, "windows", None, ["no_gpu"]),
    (1, 2048, "linux", 610, ["low_vram"]),
    (1, 8192, "windows", 552, ["old_driver"]),
    (1, 2048, "windows", 552, ["low_vram", "old_driver"]),
    (1, 8192, "mac", None, ["no_gpu"]),
    (1, None, "linux", None, []),          # unknown sizes never warn on their own
])
def test_gate_lists_reasons_but_never_blocks(count, vram, os_name, driver, reasons):
    g = nemo_diar.gate(count, vram, os_name, driver)
    assert g["reasons"] == reasons
    assert g["ok"] is (not reasons)


def test_parse_segments_accepts_strings_and_tuples_sorted():
    assert nemo_diar.parse_segments(["5.0 6.0 speaker_1", "0.5 1.25 speaker_0"]) == [
        (0.5, 1.25, 0), (5.0, 6.0, 1)]
    assert nemo_diar.parse_segments([(0.1, 0.9, 2), "bad"]) == [(0.1, 0.9, 2)]


# ---------------------------------------------------------------- choosing the diarizer

@pytest.fixture
def models(tmp_path, monkeypatch):
    """Fake standard and Nemotron diarizers; records which ran."""
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    ran = []

    def standard(audio, n, cb=None):
        ran.append("standard")
        return list(STANDARD_TURNS)

    def nemo(audio, n, cb=None):
        ran.append("nemotron")
        return list(NEMO_TURNS)

    monkeypatch.setattr(pipeline, "diarize", standard)
    monkeypatch.setattr(nemo_diar, "diarize", nemo)
    return ran


def test_default_setting_is_standard_and_never_touches_nemotron(models, monkeypatch):
    monkeypatch.setattr(nemo_diar, "diarize", lambda *a: pytest.fail("Nemotron must not run"))
    assert config.load()["diarizer"] == "standard"
    assert pipeline.diarize_labeled(AUDIO, None) == (STANDARD_TURNS, "standard")


def test_nemotron_runs_when_chosen(models):
    config.save({"diarizer": "nemotron"})
    assert pipeline.diarize_labeled(AUDIO, 3) == (NEMO_TURNS, "nemotron")
    assert models == ["nemotron"]


def test_more_than_eight_speakers_uses_standard(models):
    config.save({"diarizer": "nemotron"})
    turns, label = pipeline.diarize_labeled(AUDIO, 9)
    assert (turns, label) == (STANDARD_TURNS, "standard (over 8 speakers)")
    assert models == ["standard"]


def test_nemotron_failure_falls_back_to_standard(models, monkeypatch):
    config.save({"diarizer": "nemotron"})

    def boom(*a):
        raise RuntimeError("CUDA out of memory")
    monkeypatch.setattr(nemo_diar, "diarize", boom)
    assert pipeline.diarize_labeled(AUDIO, None) == (STANDARD_TURNS, "standard (nemotron failed)")


# ---------------------------------------------------------------- settings and setup

def test_diarizer_setting_round_trips_and_rejects_junk(client):
    assert client.get("/api/config").json()["diarizer"] == "standard"
    client.post("/api/config", json={"diarizer": "nemotron"})
    assert client.get("/api/config").json()["diarizer"] == "nemotron"
    client.post("/api/config", json={"diarizer": "whisper"})
    assert client.get("/api/config").json()["diarizer"] == "nemotron"


def test_setup_lists_nemotron_as_optional_even_when_chosen(client, monkeypatch):
    monkeypatch.setattr(server, "_gate_cache", {"ok": False, "reasons": ["no_gpu"], "vram_mb": None})
    monkeypatch.setattr(nemo_diar, "is_installed", lambda: False)
    monkeypatch.setattr(nemo_diar, "model_present", lambda: False)
    client.post("/api/config", json={"diarizer": "nemotron"})
    data = client.get("/api/setup").json()
    checks = {c["id"]: c for c in data["checks"]}
    # optional, so a missing install never locks uploads on Home
    assert checks["nemo_toolkit"]["req"] == "optional" and not checks["nemo_toolkit"]["ok"]
    assert checks["nemotron_model"]["req"] == "optional" and checks["nemotron_model"]["auto"]
    assert data["diarizer_gate"]["reasons"] == ["no_gpu"]


# ---------------------------------------------------------------- what reaches the meeting

def test_rediarize_records_which_model_labelled_the_speakers(client, upload, monkeypatch):
    mid = upload("Compare")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")
    assert "diarizer" not in client.get(f"/api/meetings/{mid}").json()["meta"]

    monkeypatch.setattr(pipeline, "rediarize_job",
                        lambda a, w, segments, n, cb: {"segments": segments, "num_speakers": 1,
                                                       "diarizer": "nemotron"})
    client.post(f"/api/meetings/{mid}/rediarize")
    meta = wait_for(lambda: (lambda m: m if m.get("diarizer") and m["status"] == "done" else None)(
        client.get(f"/api/meetings/{mid}").json()["meta"]))
    assert meta["diarizer"] == "nemotron"


def test_audio_goes_to_nemo_as_an_array_not_a_temp_file(monkeypatch):
    """File paths make NeMo write a temp manifest read by a worker process,
    which fails on Windows (WinError 32). Arrays avoid both."""
    import sys
    import types
    seen = {}

    class FakeModel:
        def diarize(self, audio, **kw):
            seen.update(audio=audio, **kw)
            return [["0.0 1.5 speaker_0", "1.5 3.0 speaker_1"]]

    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(inference_mode=lambda: __import__("contextlib").nullcontext()))
    monkeypatch.setattr(nemo_diar, "get_model", lambda: FakeModel())
    turns = nemo_diar._diarize_here(AUDIO)
    assert turns == [(0.0, 1.5, 0), (1.5, 3.0, 1)]
    assert isinstance(seen["audio"][0], np.ndarray) and seen["sample_rate"] == 16000
    assert seen["num_workers"] == 0


# ---------------------------------------------------------------- why it fell back

def test_fallback_reason_is_kept_for_the_meeting(models, monkeypatch):
    config.save({"diarizer": "nemotron"})
    pipeline.diarize_labeled(AUDIO, 2)
    assert pipeline.last_fallback is None                 # Nemotron ran: nothing to explain

    pipeline.diarize_labeled(AUDIO, 9)
    assert pipeline.last_fallback["code"] == "over_8"

    def boom(*a):
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
    monkeypatch.setattr(nemo_diar, "diarize", boom)
    pipeline.diarize_labeled(AUDIO, None)
    assert pipeline.last_fallback["code"] == "out_of_memory"
    assert "Tried to allocate" in pipeline.last_fallback["detail"]


@pytest.mark.parametrize("error, code", [
    (ModuleNotFoundError("No module named 'nemo'"), "not_installed"),
    (RuntimeError("Nemotron-3-Diarization.nemo is missing from models/ — install it"), "model_missing"),
    (ValueError("something odd"), "error"),
])
def test_fallback_reasons_are_sorted_for_people(error, code):
    assert pipeline.fallback_reason(error)["code"] == code


def test_meeting_records_the_fallback_and_a_clean_run_clears_it(client, upload, monkeypatch):
    mid = upload("Fallback")
    wait_for(lambda: client.get(f"/api/meetings/{mid}").json()["meta"]["status"] == "done")

    def rediarize(fallback):
        label = "standard (nemotron failed)" if fallback else "nemotron"
        monkeypatch.setattr(pipeline, "rediarize_job", lambda a, w, segments, n, cb: {
            "segments": segments, "num_speakers": 1, "diarizer": label, "diarizer_fallback": fallback})
        client.post(f"/api/meetings/{mid}/rediarize")
        return wait_for(lambda: (lambda m: m if m.get("diarizer") == label and m["status"] == "done" else None)(
            client.get(f"/api/meetings/{mid}").json()["meta"]))

    meta = rediarize({"code": "out_of_memory", "detail": "OutOfMemoryError: CUDA out of memory"})
    assert meta["diarizer_fallback"]["code"] == "out_of_memory"
    assert "diarizer_fallback" not in rediarize(None)


# ---------------------------------------------------------------- separate process

class _Done:
    def __init__(self, code=0, stderr=""):
        self.returncode, self.stderr, self.stdout = code, stderr, ""


def _fake_worker(monkeypatch, reply, code=0, stderr=""):
    import json
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        if reply is not None:
            from pathlib import Path
            Path(cmd[-1]).write_text(json.dumps(reply), encoding="utf-8")
        return _Done(code, stderr)
    monkeypatch.setattr(nemo_diar.subprocess, "run", run)
    return seen


def test_diarize_runs_the_model_in_its_own_process(monkeypatch):
    """PyTorch's CUDA 13 cuDNN and the CUDA 12 one Whisper/sherpa-onnx load
    cannot share a process, so the app never imports torch itself."""
    seen = _fake_worker(monkeypatch, {"turns": [[0.0, 1.5, 0], [1.5, 3.0, 1]]})
    assert nemo_diar.diarize(AUDIO, None) == [(0.0, 1.5, 0), (1.5, 3.0, 1)]
    assert seen["cmd"][1].endswith("nemo_diar.py") and seen["cmd"][2].endswith(".npy")


def test_worker_errors_keep_their_kind_for_the_fallback_reason(monkeypatch):
    _fake_worker(monkeypatch, {"error": "OutOfMemoryError", "message": "CUDA out of memory. Tried to allocate 2 GiB"}, 1)
    with pytest.raises(RuntimeError) as e:
        nemo_diar.diarize(AUDIO, None)
    assert pipeline.fallback_reason(e.value)["code"] == "out_of_memory"

    _fake_worker(monkeypatch, {"error": "ModuleNotFoundError", "message": "No module named 'nemo'"}, 1)
    with pytest.raises(ImportError):
        nemo_diar.diarize(AUDIO, None)


def test_a_worker_that_dies_silently_still_explains_itself(monkeypatch):
    _fake_worker(monkeypatch, None, 3221225477, "Windows fatal exception: access violation")
    with pytest.raises(RuntimeError, match="exit code 3221225477.*access violation"):
        nemo_diar.diarize(AUDIO, None)
