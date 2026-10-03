"""One-click setup: per-item state, failure messages, the concurrency guard and the
manual-only rule. Every install step is a fake: nothing here installs or downloads."""

import threading

import pytest

import installer
import server
from conftest import wait_for

LOCAL_IDS = ("core", "faster_whisper", "ctranslate2", "sherpa_onnx", "ffmpeg",
             "whisper_model", "seg_model", "emb_model")


def check(cid, ok, req="always"):
    return {"id": cid, "name": cid, "ok": ok, "detail": "", "hint": "", "req": req,
            "auto": cid in installer.STEP_IDS, "fix": {"windows": [], "linux": []}}


class World:
    """A fake machine: which checks are satisfied, and fake steps that fix them."""

    def __init__(self, missing=(), engine="local"):
        self.ok = {cid: cid not in missing for cid in LOCAL_IDS}
        self.engine = engine
        self.ran = []
        self.fail = {}          # id -> message
        self.gates = {}         # id -> Event the step waits on
        self.entered = {}       # id -> Event set when the step starts
        for cid in LOCAL_IDS:
            self.entered[cid] = threading.Event()

    def evaluate(self):
        checks = [check(c, ok, "always" if c in ("core", "ffmpeg") else "local") for c, ok in self.ok.items()]
        checks += [check("cuda", False, "optional"), check("ollama", False, "optional"),
                   check("gemini_key", False, "gemini"), check("disk", True),
                   check("python", True)]
        return {"checks": checks, "engine": self.engine}

    def step(self, cid):
        def run(report):
            self.ran.append(cid)
            self.entered[cid].set()
            report(0.5, "halfway")
            if cid in self.gates:
                assert self.gates[cid].wait(10)
            if cid in self.fail:
                raise RuntimeError(self.fail[cid])
            self.ok[cid] = True
        return run

    def installer(self, steps=None):
        return installer.Installer(steps or {c: self.step(c) for c in installer.STEP_IDS}, self.evaluate)


@pytest.fixture
def world(monkeypatch):
    def make(**kw):
        w = World(**kw)
        monkeypatch.setattr(server, "setup_installer", w.installer())
        return w
    return make


def finished(client):
    return wait_for(lambda: (lambda s: s if not s["running"] else None)(client.get("/api/setup/install").json()))


def test_default_run_queues_only_missing_items_the_engine_needs(client, world):
    w = world(missing={"ffmpeg", "seg_model"})
    r = client.post("/api/setup/install").json()
    assert r["started"] is True and r["queued"] == ["ffmpeg", "seg_model"]
    snap = finished(client)
    assert w.ran == ["ffmpeg", "seg_model"]
    assert {k: v["state"] for k, v in snap["items"].items()} == {"ffmpeg": "done", "seg_model": "done"}


def test_engine_gemini_skips_local_only_items(client, world):
    w = world(missing={"whisper_model", "ffmpeg"}, engine="gemini")
    client.post("/api/setup/install")
    finished(client)
    assert w.ran == ["ffmpeg"]


def test_nothing_missing_starts_nothing(client, world):
    world(missing=())
    r = client.post("/api/setup/install").json()
    assert r["started"] is False and r["queued"] == []
    assert client.get("/api/setup/install").json()["items"] == {}


def test_states_go_pending_running_done_with_progress(client, world):
    w = world(missing={"ffmpeg", "emb_model"})
    w.gates["ffmpeg"] = threading.Event()
    client.post("/api/setup/install")
    assert w.entered["ffmpeg"].wait(10)
    snap = wait_for(lambda: (lambda s: s if s["items"]["ffmpeg"]["progress"] == 0.5 else None)(
        client.get("/api/setup/install").json()))
    assert snap["running"] is True
    assert snap["items"]["ffmpeg"]["state"] == "running"
    assert snap["items"]["ffmpeg"]["message"] == "halfway"
    assert snap["items"]["emb_model"]["state"] == "pending"
    w.gates["ffmpeg"].set()
    snap = finished(client)
    assert snap["items"]["ffmpeg"]["state"] == "done" and snap["items"]["emb_model"]["state"] == "done"


def test_failure_carries_its_message_and_the_run_continues(client, world):
    w = world(missing={"ffmpeg", "emb_model"})
    w.fail["ffmpeg"] = "network unreachable"
    client.post("/api/setup/install")
    items = finished(client)["items"]
    assert items["ffmpeg"]["state"] == "failed" and items["ffmpeg"]["message"] == "network unreachable"
    assert items["emb_model"]["state"] == "done"


def test_retry_after_failure_succeeds(client, world):
    w = world(missing={"emb_model"})
    w.fail["emb_model"] = "boom"
    client.post("/api/setup/install", json={"ids": ["emb_model"]})
    assert finished(client)["items"]["emb_model"]["state"] == "failed"
    del w.fail["emb_model"]
    client.post("/api/setup/install", json={"ids": ["emb_model"]})
    assert finished(client)["items"]["emb_model"]["state"] == "done"


def test_step_that_leaves_the_check_failing_is_reported_failed(client, monkeypatch):
    w = World(missing={"ffmpeg"})
    monkeypatch.setattr(server, "setup_installer",
                        w.installer({c: (lambda report: None) for c in installer.STEP_IDS}))
    client.post("/api/setup/install", json={"ids": ["ffmpeg"]})
    item = finished(client)["items"]["ffmpeg"]
    assert item["state"] == "failed" and "still reports" in item["message"]


def test_dependent_step_is_skipped_when_its_package_failed(client, world):
    w = world(missing={"faster_whisper", "whisper_model"})
    w.fail["faster_whisper"] = "pip exploded"
    client.post("/api/setup/install")
    items = finished(client)["items"]
    assert items["faster_whisper"]["state"] == "failed"
    assert items["whisper_model"]["state"] == "failed" and "faster_whisper" in items["whisper_model"]["message"]
    assert "whisper_model" not in w.ran


def test_second_request_during_a_run_merges_into_it(client, world):
    w = world(missing={"ffmpeg", "emb_model", "seg_model"})
    w.gates["ffmpeg"] = threading.Event()
    first = client.post("/api/setup/install", json={"ids": ["ffmpeg"]}).json()
    assert first["started"] is True
    assert w.entered["ffmpeg"].wait(10)
    second = client.post("/api/setup/install", json={"ids": ["ffmpeg", "emb_model"]}).json()
    assert second["started"] is False and second["merged"] is True
    assert second["queued"] == ["emb_model"]          # ffmpeg is already running, not re-queued
    third = client.post("/api/setup/install").json()  # default also merges
    assert third["queued"] == ["seg_model"]
    assert len([t for t in threading.enumerate() if t.name == "setup-installer"]) == 1
    w.gates["ffmpeg"].set()
    items = finished(client)["items"]
    assert w.ran == ["ffmpeg", "emb_model", "seg_model"]
    assert all(v["state"] == "done" for v in items.values())


def test_manual_items_are_rejected_and_never_run(client, world):
    w = world(missing={"ffmpeg"})
    for cid in ("cuda", "ollama", "gemini_key", "disk", "python", "nonsense"):
        r = client.post("/api/setup/install", json={"ids": [cid]})
        assert r.status_code == 400, cid
    assert w.ran == []
    assert client.get("/api/setup/install").json()["items"] == {}


def test_bad_body_is_rejected(client, world):
    world()
    assert client.post("/api/setup/install", json={"ids": "ffmpeg"}).status_code == 400


def test_setup_endpoint_reports_install_state_and_auto_flags(client, world):
    world(missing={"emb_model"})
    client.post("/api/setup/install")
    finished(client)
    data = client.get("/api/setup").json()
    assert data["install"]["items"]["emb_model"]["state"] == "done"
    assert data["compute"] in ("gpu", "cpu")
    auto = {c["id"]: c["auto"] for c in data["checks"]}
    assert auto["ffmpeg"] and auto["whisper_model"] and auto["seg_model"] and auto["emb_model"]
    assert not any(auto[i] for i in ("cuda", "ollama", "gemini_key", "disk", "python"))


def test_registry_covers_exactly_the_unattended_items():
    assert set(installer.default_steps()) == installer.STEP_IDS
    assert not {"cuda", "ollama", "gemini_key", "disk", "python"} & installer.STEP_IDS
