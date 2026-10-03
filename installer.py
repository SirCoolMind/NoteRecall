"""One-click setup: unattended install steps and the background runner.

STEPS is a registry keyed by the same ids as the checks in server._evaluate.
Items that need the user (python itself, CUDA drivers, Ollama, the Gemini key,
disk space) are deliberately NOT in it: they only ever get manual instructions.

Installer runs the chosen steps one after another in a single background
thread and re-runs the checks after each one. Steps and the checks function
are injected, so tests drive it with fakes and never install or download.
"""

import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).parent

# Run order: packages first (later steps import them), then the big downloads.
ORDER = ["core", "faster_whisper", "ctranslate2", "sherpa_onnx", "ffmpeg",
         "whisper_model", "seg_model", "emb_model"]
STEP_IDS = frozenset(ORDER)
# A step is pointless when one of these failed earlier in the same run.
DEPENDS = {"whisper_model": ("faster_whisper",)}

# Same files start.sh / start.bat fetch.
_RELEASES = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEG_URL = f"{_RELEASES}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMB_URL = f"{_RELEASES}/speaker-recongition-models/nemo_en_titanet_large.onnx"

MESSAGE_MAX = 400


# ---------------------------------------------------------------- steps

def _tail(text: str, limit: int = MESSAGE_MAX) -> str:
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return " | ".join(lines[-3:])[-limit:] or "no output"


def _pip_install(args: list, report) -> None:
    """Install into the interpreter running the server: uv if present (uv venvs
    ship without pip), otherwise pip."""
    uv = shutil.which("uv")
    if uv:
        cmd = [uv, "pip", "install", "--python", sys.executable, *args]
    else:
        if importlib.util.find_spec("pip") is None:
            subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        cmd = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *args]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       cwd=BASE_DIR, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError(_tail(r.stderr or r.stdout))
    importlib.invalidate_caches()  # let this process see what was just installed


def _mb(n: float) -> str:
    return f"{n / 1e6:,.0f} MB"


def _download(url: str, dest: Path, report) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
                done += len(chunk)
                report(done / total if total else None,
                       f"{_mb(done)} / {_mb(total)}" if total else _mb(done))
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def _safe_extract(archive: Path, dest: Path) -> None:
    root = dest.resolve()
    with tarfile.open(archive, "r:*") as tf:
        members = tf.getmembers()
        for m in members:
            target = (dest / m.name).resolve()
            if m.issym() or m.islnk() or (target != root and root not in target.parents):
                raise RuntimeError(f"unsafe path in archive: {m.name}")
        kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
        tf.extractall(dest, members=members, **kwargs)


def step_requirements(report):
    _pip_install(["-r", str(BASE_DIR / "requirements.txt")], report)


def step_ctranslate2(report):
    _pip_install(["ctranslate2"], report)


def step_ffmpeg(report):
    _pip_install(["imageio-ffmpeg"], report)
    import ffmpeg_tools
    import pipeline
    pipeline.FFMPEG = ffmpeg_tools.ffmpeg_exe()  # pipeline resolved it at import, before it existed


def whisper_cache_dir(model: str) -> Path:
    """Where huggingface_hub keeps the model; honours HF_HOME / HF_HUB_CACHE.
    faster-whisper downloads (and WhisperModel loads) from this same cache."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        hub = Path(HF_HUB_CACHE)
    except Exception:
        hub = Path(os.environ.get("HF_HUB_CACHE")
                   or os.environ.get("HUGGINGFACE_HUB_CACHE")
                   or Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub")
    return hub / f"models--Systran--faster-whisper-{model}"


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def step_whisper_model(report):
    import config
    model = config.load().get("whisper_model", "large-v3")
    from faster_whisper.utils import download_model  # faster-whisper's own downloader
    stop = threading.Event()

    def watch():  # the library gives no byte counts; show what has landed on disk
        while not stop.wait(1.0):
            report(None, _mb(_dir_size(whisper_cache_dir(model))))

    threading.Thread(target=watch, daemon=True).start()
    try:
        download_model(model)
    finally:
        stop.set()


def step_seg_model(report):
    import pipeline
    archive = pipeline.MODELS_DIR / "seg.tar.bz2"
    try:
        _download(SEG_URL, archive, report)
        report(None, "")
        _safe_extract(archive, pipeline.MODELS_DIR)
    finally:
        archive.unlink(missing_ok=True)
    if not pipeline.SEG_MODEL.exists():
        raise RuntimeError(f"archive unpacked but {pipeline.SEG_MODEL.name} is not where NoteRecall expects it")


def step_emb_model(report):
    import pipeline
    _download(EMB_URL, pipeline.EMB_MODEL, report)


def default_steps() -> dict:
    return {
        "core": step_requirements,
        "faster_whisper": step_requirements,
        "sherpa_onnx": step_requirements,
        "ctranslate2": step_ctranslate2,
        "ffmpeg": step_ffmpeg,
        "whisper_model": step_whisper_model,
        "seg_model": step_seg_model,
        "emb_model": step_emb_model,
    }


# ---------------------------------------------------------------- runner

class Installer:
    """steps: {check id: fn(report)}, where report(progress 0..1 or None, message="").
    evaluate: () -> {"checks": [...], "engine": "local" | "gemini"} (server._evaluate)."""

    def __init__(self, steps: dict, evaluate):
        self._steps = steps
        self._evaluate = evaluate
        self._lock = threading.Lock()
        self._items: dict = {}
        self._queue: list = []
        self._running = False

    # -- state
    def snapshot(self) -> dict:
        with self._lock:
            return {"running": self._running, "order": list(ORDER),
                    "items": {k: dict(v) for k, v in self._items.items()}}

    def _set(self, cid, **fields):
        with self._lock:
            self._items.setdefault(cid, {"state": "pending", "message": "", "progress": None}).update(fields)

    def _checks(self):
        res = self._evaluate()
        return {c["id"]: c for c in res["checks"]}, res.get("engine", "local")

    def missing_unattended(self) -> list:
        """Missing items the current engine needs that a step can fix."""
        checks, engine = self._checks()
        return [cid for cid in self._ordered(checks)
                if cid in self._steps and not checks[cid]["ok"]
                and checks[cid].get("req") in ("always", engine)]

    @staticmethod
    def _ordered(ids):
        ids = set(ids)
        return [c for c in ORDER if c in ids] + sorted(ids - set(ORDER))

    # -- control
    def start(self, ids=None) -> dict:
        """Queue steps. Returns {started, merged, queued, install}. A call while a run
        is active is merged into it instead of starting a second thread."""
        if ids is None:
            ids = self.missing_unattended()
        else:
            bad = [i for i in ids if i not in self._steps]
            if bad:
                raise ValueError("not installable automatically (manual steps only): " + ", ".join(bad))
        ids = self._ordered(dict.fromkeys(ids))
        with self._lock:
            if self._running:
                fresh = [i for i in ids if i not in self._queue
                         and self._items.get(i, {}).get("state") != "running"]
                for i in fresh:
                    self._items[i] = {"state": "pending", "message": "", "progress": None}
                self._queue.extend(fresh)
                started, merged, queued = False, True, fresh
            elif not ids:
                started, merged, queued = False, False, []
            else:
                self._items = {k: v for k, v in self._items.items()
                               if v["state"] != "done" and k not in ids}
                for i in ids:
                    self._items[i] = {"state": "pending", "message": "", "progress": None}
                self._queue = list(ids)
                self._running = True
                threading.Thread(target=self._run, daemon=True, name="setup-installer").start()
                started, merged, queued = True, False, ids
        return {"started": started, "merged": merged, "queued": queued, "install": self.snapshot()}

    def _run(self):
        try:
            while True:
                with self._lock:
                    if not self._queue:
                        self._running = False
                        return
                    cid = self._queue.pop(0)
                    self._items[cid].update(state="running", message="", progress=None)
                self._do(cid)
        finally:
            with self._lock:
                self._running = False
                for it in self._items.values():  # only reachable on a crash
                    if it["state"] in ("pending", "running"):
                        it.update(state="failed", message="setup stopped unexpectedly")

    def _do(self, cid):
        for dep in DEPENDS.get(cid, ()):
            if self._items.get(dep, {}).get("state") == "failed":
                self._set(cid, state="failed", message=f"skipped: it needs {dep} first")
                return
        try:
            if self._is_ok(cid) is True:
                self._set(cid, state="done", message="already in place", progress=1)
                return
            self._steps[cid](lambda p=None, m="": self._set(
                cid, progress=None if p is None else round(float(p), 3), message=str(m)[:MESSAGE_MAX]))
        except Exception as e:  # any failure becomes the item's message; the run goes on
            self._set(cid, state="failed", message=(str(e) or e.__class__.__name__)[:MESSAGE_MAX])
            return
        if self._is_ok(cid) is False:  # the step finished but the check still disagrees
            self._set(cid, state="failed", message="installed, but the check still reports it missing")
        else:
            self._set(cid, state="done", message="", progress=1)

    def _is_ok(self, cid):
        """Re-run the checks. None when they could not be run."""
        try:
            checks, _ = self._checks()
            return bool(checks[cid]["ok"])
        except Exception:
            return None
