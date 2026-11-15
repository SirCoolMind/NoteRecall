"""Local meeting transcription app — FastAPI server.

Run:  .venv\\Scripts\\python.exe server.py   then open http://localhost:8756
"""

import asyncio
import json
import os
import queue
import shutil
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import config
import corrections
import timing
import engines
import ffmpeg_tools
import installer as installer_mod
import linkfetch
import nemo_diar
import pipeline
import search as search_mod
import summarizer
import updater as updater_mod
from version import __version__

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="NoteRecall")
jobs: "queue.Queue[str]" = queue.Queue()
live_status: dict[str, dict] = {}  # id -> {stage, progress}
# id -> lines transcribed so far in the running job. Memory only: nothing is
# written until the job finishes, so an interrupted job leaves no half transcript.
live_lines: dict[str, list] = {}


# ---------------------------------------------------------------- storage

def meeting_dir(mid: str) -> Path:
    d = DATA_DIR / mid
    if not d.is_dir():
        raise HTTPException(404, "meeting not found")
    return d


def read_meta(mid: str) -> dict:
    p = meeting_dir(mid) / "meta.json"
    for attempt in range(3):
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            if attempt == 2:
                raise
            time.sleep(0.05)


_meta_locks: dict[str, threading.RLock] = {}
_meta_locks_guard = threading.Lock()
USER_FIELDS = ("title", "speaker_names")  # editable by the user at any time


def meta_lock(mid: str) -> threading.RLock:
    """Per-meeting lock: serialises every read-modify-write of meta.json."""
    with _meta_locks_guard:
        return _meta_locks.setdefault(mid, threading.RLock())


def write_meta(mid: str, meta: dict):
    with meta_lock(mid):
        _write_meta_unlocked(mid, meta)


def merge_user_fields(mid: str, meta: dict, skip=()):
    """Pull user-editable fields from disk into the worker's stale copy.
    Caller must hold meta_lock(mid)."""
    try:
        disk = read_meta(mid)
    except Exception:
        return
    for k in USER_FIELDS:
        if k in disk and k not in skip:
            meta[k] = disk[k]


def _write_meta_unlocked(mid: str, meta: dict):
    # atomic: write to temp file then replace, so readers never see a partial file
    p = DATA_DIR / mid / "meta.json"
    tmp = p.with_suffix(".json.tmp")
    data = json.dumps(meta, ensure_ascii=False, indent=1)
    tmp.write_text(data, encoding="utf-8")
    for _ in range(25):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            # Windows: replace fails while a reader has the file open
            time.sleep(0.02)
    tmp.unlink(missing_ok=True)
    p.write_text(data, encoding="utf-8")  # last resort, non-atomic


def _replace_file(tmp: Path, p: Path, data: str):
    for _ in range(25):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:
            # Windows: replace fails while a reader has the file open
            time.sleep(0.02)
    tmp.unlink(missing_ok=True)
    p.write_text(data, encoding="utf-8")  # last resort, non-atomic


def write_transcript(mid: str, segments: list):
    """Atomic like meta.json, so a reader never sees half a transcript."""
    p = DATA_DIR / mid / "transcript.json"
    tmp = p.with_suffix(".json.tmp")
    data = json.dumps(segments, ensure_ascii=False)
    tmp.write_text(data, encoding="utf-8")
    _replace_file(tmp, p, data)


def read_transcript(mid: str) -> list[dict]:
    p = meeting_dir(mid) / "transcript.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def speaker_label(meta: dict, spk: int) -> str:
    if spk < 0:
        return "?"
    return meta.get("speaker_names", {}).get(str(spk), f"Speaker {spk + 1}")


# ---------------------------------------------------------------- worker

def _note_diarizer(meta: dict, result: dict):
    """Which speaker model ran, and when Nemotron-3 was chosen but Standard ran
    instead, why (diarizer_fallback: {"code", "detail"}); a clean run clears it."""
    if result.get("diarizer"):
        meta["diarizer"] = result["diarizer"]
    if result.get("diarizer_fallback"):
        meta["diarizer_fallback"] = result["diarizer_fallback"]
    else:
        meta.pop("diarizer_fallback", None)


def _has_audio(d: Path, meta: dict) -> bool:
    name = meta.get("audio_file")
    return bool(name) and (d / name).is_file()


DOWNLOAD_SHARE = 4   # a link's download fills 0..4 %, just under "converting"


def _fetch_link(mid: str, d: Path, meta: dict, status):
    """Download a link meeting's audio (worker thread). Raises linkfetch.LinkError."""
    status("downloading", 0)
    got = linkfetch.fetch(meta["source_url"], d,
                          lambda f: status("downloading", f * DOWNLOAD_SHARE))
    meta["audio_file"] = got["file"]
    with meta_lock(mid):
        merge_user_fields(mid, meta)
        # the video's own title, unless the user typed one or renamed it meanwhile
        if got["title"] and meta.get("title") == linkfetch.PLACEHOLDER_TITLE:
            meta["title"] = got["title"]
        _write_meta_unlocked(mid, meta)


def worker():
    while True:
        kind, mid, arg = jobs.get()
        d = DATA_DIR / mid
        try:
            meta = read_meta(mid)
        except Exception:
            jobs.task_done()
            continue

        def status(stage, progress):
            progress = round(progress)
            changed = (meta.get("status") != stage or meta.get("progress") != progress)
            meta["status"], meta["progress"] = stage, progress
            if changed:  # progress callbacks fire very often; only hit disk on change
                with meta_lock(mid):
                    merge_user_fields(mid, meta)
                    _write_meta_unlocked(mid, meta)
            # after the file: a reader that sees "error" here must also find the reason on disk
            live_status[mid] = {"stage": stage, "progress": progress}

        def line(seg):
            live_lines.setdefault(mid, []).append(
                {"start": seg.get("start", 0), "text": seg.get("text", "")})

        # run_job only takes the status callback, so the line callback rides on it
        status.line = line

        try:
            t0 = time.time()
            if kind == "rediarize":
                segments = read_transcript(mid)
                result = pipeline.rediarize_job(
                    d / meta["audio_file"], d, segments, arg or None, status)
                meta["num_speakers"] = arg or 0
                _note_diarizer(meta, result)
                # re-detecting speakers intentionally resets the names; persist
                # the reset now so later merges pick up the empty dict from disk
                with meta_lock(mid):
                    merge_user_fields(mid, meta, skip=("speaker_names",))
                    meta["speaker_names"] = {}
                    _write_meta_unlocked(mid, meta)
            else:
                if meta.get("source_url") and not _has_audio(d, meta):
                    _fetch_link(mid, d, meta, status)
                result = pipeline.run_job(
                    d / meta["audio_file"], d,
                    meta.get("language") or None,
                    meta.get("num_speakers") or None,
                    status,
                )
                meta.update(duration=result["duration"],
                            detected_language=result["language"])
                if result.get("speakers_by"):
                    meta["speakers_by"] = result["speakers_by"]
                _note_diarizer(meta, result)
                if result.get("chunks"):
                    meta["chunks"] = result["chunks"]
            # clustering returns arbitrary ids; present them as Speaker 1..N
            n_speakers = pipeline.compact_speakers(result["segments"])
            write_transcript(mid, result["segments"])
            # a fresh transcript or fresh speakers is the new original
            corrections.drop_backup(d)
            meta.pop("summary_stale", None)
            meta.update(
                num_speakers_found=n_speakers or result["num_speakers"],
                processing_seconds=round(time.time() - t0),
            )
            with meta_lock(mid):
                merge_user_fields(mid, meta)
            summary, engine = summarizer.summarize(
                result["segments"], meta.get("speaker_names", {}))
            (d / "summary.md").write_text(summary, encoding="utf-8")
            meta["summary_engine"] = engine
            meta.pop("error", None)
            meta.pop("error_code", None)
            live_lines.pop(mid, None)   # before "done" is visible: the real transcript takes over
            status("done", 100)
        except Exception as e:
            import traceback
            traceback.print_exc()
            meta["error"] = str(e)
            # link failures carry a code the screens translate; anything else clears it
            if isinstance(e, linkfetch.LinkError):
                meta["error_code"] = "link_" + e.code
            else:
                meta.pop("error_code", None)
            live_lines.pop(mid, None)
            status("error", 0)
        finally:
            live_status.pop(mid, None)
            live_lines.pop(mid, None)
            jobs.task_done()


_worker_started = False
_worker_start_lock = threading.Lock()


def requeue_unfinished():
    """Jobs interrupted by a server restart get re-run from scratch."""
    for d in sorted(DATA_DIR.iterdir()):
        mp = d / "meta.json"
        if not mp.exists():
            continue
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            continue
        if m.get("status") not in ("done", "error"):
            print(f"[server] re-queuing interrupted job {m['id']}", flush=True)
            jobs.put(("full", m["id"], None))


def start_background():
    """Start the worker thread (once) and re-queue interrupted jobs.
    Runs at app startup, not at import, so tests can point DATA_DIR elsewhere."""
    global _worker_started
    with _worker_start_lock:
        if _worker_started:
            return
        _worker_started = True
        DATA_DIR.mkdir(exist_ok=True)
        threading.Thread(target=worker, daemon=True).start()
        requeue_unfinished()


def _quiet_connection_resets(loop, context):
    """Windows: a browser tab closing or reloading mid-request makes asyncio print
    a ConnectionResetError traceback (WinError 10054). It is harmless; drop it."""
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


@asynccontextmanager
async def lifespan(_app):
    pipeline._preload_sherpa_ort()   # before anything loads the pip onnxruntime
    asyncio.get_running_loop().set_exception_handler(_quiet_connection_resets)
    start_background()
    yield


app.router.lifespan_context = lifespan


# ---------------------------------------------------------------- api

# Vendored CSS, JS, fonts, icons and i18n dictionaries (no CDN, works offline).
class FreshStatic(StaticFiles):
    """Static files the browser must re-check every time (a cheap 304 when unchanged).
    Without this a browser keeps old scripts for a while after an update and runs
    them against the new page."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", FreshStatic(directory=BASE_DIR / "static"), name="static")


@app.get("/",response_class=HTMLResponse)
def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


# The old standalone pages now live inside the Settings drawer of the app shell.
@app.get("/about")
def about():
    return RedirectResponse("/#settings/about")


@app.get("/setup")
def setup_page():
    return RedirectResponse("/#settings")


@app.get("/api/status")
def api_status():
    cfg = config.load()
    return {
        "version": __version__,
        "device": pipeline._whisper_device or "not loaded yet",
        "ollama_model": summarizer.ollama_model(),
        "queue_size": jobs.qsize(),
        "engine": cfg["engine"],
        "gemini_model": cfg["gemini_model"],
    }


def _is_masked_key(value: str) -> bool:
    """The browser only ever sees a masked key; a value that still looks masked
    (or is the "set" placeholder) is that echo coming back, never a real key."""
    return "…" in value or "•" in value or value.strip().lower() == "set"


@app.get("/api/config")
def get_config():
    cfg = config.load()
    key = cfg.pop("gemini_api_key", "") or ""
    # Never send the key itself back: only whether one exists and its last 4 characters.
    cfg["has_key"] = bool(key)
    cfg["gemini_api_key_masked"] = ("…" + key[-4:]) if len(key) > 8 else ("set" if key else "")
    return cfg


@app.post("/api/config")
def set_config(body: dict):
    allowed = {}
    if body.get("engine") in ("local", "gemini"):
        allowed["engine"] = body["engine"]
    if isinstance(body.get("gemini_model"), str) and body["gemini_model"].strip():
        allowed["gemini_model"] = body["gemini_model"].strip()
    if body.get("device") in ("auto", "cpu"):
        allowed["device"] = body["device"]
    if body.get("whisper_model") in ("large-v3", "medium", "small", "base"):
        allowed["whisper_model"] = body["whisper_model"]
    if body.get("diarizer") in ("standard", "nemotron"):
        allowed["diarizer"] = body["diarizer"]
    if isinstance(body.get("youtube_links"), bool):
        allowed["youtube_links"] = body["youtube_links"]
    if body.get("default_language") in ("", "ms", "en"):
        allowed["default_language"] = body["default_language"]
    n = body.get("default_speakers")
    if isinstance(n, str) and n.strip().isdigit():
        n = int(n.strip())
    if isinstance(n, int) and not isinstance(n, bool) and 0 <= n <= 8:
        allowed["default_speakers"] = n
    # only overwrite the stored key if a new one was actually typed (not the masked echo)
    if isinstance(body.get("gemini_api_key"), str):
        typed = body["gemini_api_key"].strip()
        if typed and not _is_masked_key(typed):
            allowed["gemini_api_key"] = typed
    config.save(allowed)
    return get_config()


@app.post("/api/config/test-gemini")
def test_gemini(body: dict = None):
    cfg = config.load()
    key = (body or {}).get("gemini_api_key", "").strip() or cfg.get("gemini_api_key", "")
    if not key:
        return {"ok": False, "message": "No API key entered"}
    return engines.test_key(key, cfg.get("gemini_model", "gemini-2.5-flash"))


# venv paths differ per platform. These must follow the OS the instruction is
# FOR (the page lets you view either), not the OS the server happens to run on.
WIN_PY, WIN_PIP = r".venv\Scripts\python.exe", r".venv\Scripts\pip.exe"
LNX_PY, LNX_PIP = "./.venv/bin/python", "./.venv/bin/pip"


def _py(name: str = "") -> str:
    """The interpreter path for THIS machine (used in the AI prompt)."""
    return WIN_PY if os.name == "nt" else LNX_PY


# Per-check installation steps. Keyed by check id; each OS gets ordered steps.
# A step is {"do": human instruction, "cmd": command to run (optional)}.
def _fixes(cfg: dict) -> dict:
    wm = cfg.get("whisper_model", "large-v3")

    def dl_whisper(py):
        return (f'{py} -c "from huggingface_hub import snapshot_download; '
                f"snapshot_download('Systran/faster-whisper-{wm}')\"")

    return {
        "python": {
            "windows": [{"do": "Install Python 3.10 or newer, then re-create the virtual environment",
                         "cmd": "winget install -e --id Python.Python.3.13"},
                        {"do": "Create the virtual environment in the app folder",
                         "cmd": "py -3 -m venv .venv"}],
            "linux": [{"do": "Install Python 3 and the venv module. On Debian/Ubuntu the venv "
                             "module is a SEPARATE package — without it 'python3 -m venv' fails "
                             "with “ensurepip is not available”",
                       "cmd": "sudo apt install -y python3 python3-venv python3-pip"},
                      {"do": "Create the virtual environment in the app folder",
                       "cmd": "python3 -m venv .venv"}],
        },
        "core": {
            "windows": [{"do": "Install the web-server packages", "cmd": f"{WIN_PIP} install -r requirements.txt"}],
            "linux": [{"do": "Install the web-server packages", "cmd": f"{LNX_PIP} install -r requirements.txt"}],
        },
        "ffmpeg": {
            "windows": [{"do": "Install the bundled ffmpeg", "cmd": f"{WIN_PIP} install imageio-ffmpeg"},
                        {"do": "ffmpeg is bundled via requirements.txt (imageio-ffmpeg); a manual install is optional",
                         "cmd": "winget install -e --id Gyan.FFmpeg"},
                        {"do": "Optional: after a manual install, reopen your terminal and check it is on PATH",
                         "cmd": "ffmpeg -version"}],
            "linux": [{"do": "Install the bundled ffmpeg", "cmd": f"{LNX_PIP} install imageio-ffmpeg"},
                      {"do": "Bundled via requirements.txt; manual install is optional — Debian/Ubuntu", "cmd": "sudo apt install -y ffmpeg"},
                      {"do": "Fedora/RHEL", "cmd": "sudo dnf install -y ffmpeg"},
                      {"do": "Arch", "cmd": "sudo pacman -S ffmpeg"},
                      {"do": "Verify", "cmd": "ffmpeg -version"}],
        },
        "faster_whisper": {
            "windows": [{"do": "Install the Whisper engine (also brings CTranslate2 and Silero VAD)",
                         "cmd": f"{WIN_PIP} install faster-whisper"}],
            "linux": [{"do": "Install the Whisper engine (also brings CTranslate2 and Silero VAD)",
                       "cmd": f"{LNX_PIP} install faster-whisper"}],
        },
        "ctranslate2": {
            "windows": [{"do": "Comes with faster-whisper; install it directly if missing",
                         "cmd": f"{WIN_PIP} install ctranslate2"}],
            "linux": [{"do": "Comes with faster-whisper; install it directly if missing",
                       "cmd": f"{LNX_PIP} install ctranslate2"}],
        },
        "sherpa_onnx": {
            "windows": [{"do": "Install the speaker-detection runtime (CPU only, no PyTorch)",
                         "cmd": f"{WIN_PIP} install sherpa-onnx"}],
            "linux": [{"do": "Install the speaker-detection runtime (CPU only, no PyTorch)",
                       "cmd": f"{LNX_PIP} install sherpa-onnx"}],
        },
        "cuda": {
            "windows": [{"do": "Only for NVIDIA GPUs. First check the driver sees your card", "cmd": "nvidia-smi"},
                        {"do": "Install the CUDA libraries (~2.3 GB — skip on CPU-only machines)",
                         "cmd": f"{WIN_PIP} install -r requirements-gpu.txt"},
                        {"do": "No NVIDIA GPU? Nothing to install — choose “CPU only” above and a "
                               "smaller Whisper model. The app works fine, just slower."}],
            "linux": [{"do": "Only for NVIDIA GPUs. First check the driver sees your card", "cmd": "nvidia-smi"},
                      {"do": "If nvidia-smi is missing, install the driver (Ubuntu)",
                       "cmd": "sudo ubuntu-drivers autoinstall && sudo reboot"},
                      {"do": "Install the CUDA libraries (~2.3 GB — skip on CPU-only servers)",
                       "cmd": f"{LNX_PIP} install -r requirements-gpu.txt"},
                      {"do": "No NVIDIA GPU? Nothing to install — choose “CPU only” above and a "
                             "smaller Whisper model. The app works fine, just slower."}],
        },
        "whisper_model": {
            "windows": [{"do": "It downloads by itself on the first local transcription. To fetch it now",
                         "cmd": dl_whisper(WIN_PY)}],
            "linux": [{"do": "It downloads by itself on the first local transcription. To fetch it now",
                       "cmd": dl_whisper(LNX_PY)}],
        },
        "seg_model": {
            "windows": [{"do": "Download the speaker segmentation model into models\\",
                         "cmd": "curl.exe -L -o models\\seg.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"},
                        {"do": "Unpack it", "cmd": "tar -xjf models\\seg.tar.bz2 -C models"}],
            "linux": [{"do": "Download the speaker segmentation model into models/",
                       "cmd": "mkdir -p models && curl -L -o models/seg.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"},
                      {"do": "Unpack it", "cmd": "tar -xjf models/seg.tar.bz2 -C models && rm models/seg.tar.bz2"}],
        },
        "emb_model": {
            "windows": [{"do": "Download the voice-fingerprint model into models\\",
                         "cmd": "curl.exe -L -o models\\nemo_en_titanet_large.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_large.onnx"}],
            "linux": [{"do": "Download the voice-fingerprint model into models/",
                       "cmd": "mkdir -p models && curl -L -o models/nemo_en_titanet_large.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/nemo_en_titanet_large.onnx"}],
        },
        "ollama": {
            "windows": [{"do": "Optional — gives proper AI-written summaries instead of extractive ones",
                         "cmd": "winget install -e --id Ollama.Ollama"},
                        {"do": "Pull a model that handles Malay well (~4.7 GB)", "cmd": "ollama pull qwen2.5:7b"}],
            "linux": [{"do": "Optional — gives proper AI-written summaries instead of extractive ones",
                       "cmd": "curl -fsSL https://ollama.com/install.sh | sh"},
                      {"do": "Pull a model that handles Malay well (~4.7 GB)", "cmd": "ollama pull qwen2.5:7b"}],
        },
        "gemini_key": {
            "windows": [{"do": "Create a free API key at https://aistudio.google.com/apikey, then paste it in the Google Gemini settings above and press Save"}],
            "linux": [{"do": "Create a free API key at https://aistudio.google.com/apikey, then paste it in the Google Gemini settings above and press Save"}],
        },
        "nemo_toolkit": {
            "windows": [{"do": "Optional, experimental. Easiest: Settings → Speakers → Nemotron-3 → Install now. "
                               "By hand: PyTorch first (CUDA build for NVIDIA cards), then the NeMo packages",
                         "cmd": f"{WIN_PIP} install torch --index-url {installer_mod.TORCH_CUDA_INDEX}"},
                        {"do": "Then", "cmd": f"{WIN_PIP} install -r requirements-nemo.txt"}],
            "linux": [{"do": "Optional, experimental. Easiest: Settings → Speakers → Nemotron-3 → Install now. "
                             "By hand: PyTorch first (CUDA build for NVIDIA cards), then the NeMo packages",
                       "cmd": f"{LNX_PIP} install torch --index-url {installer_mod.TORCH_CUDA_INDEX}"},
                      {"do": "Then", "cmd": f"{LNX_PIP} install -r requirements-nemo.txt"}],
        },
        "yt_dlp": {
            "windows": [{"do": "Install or update the YouTube downloader", "cmd": f"{WIN_PIP} install -U yt-dlp"}],
            "linux": [{"do": "Install or update the YouTube downloader", "cmd": f"{LNX_PIP} install -U yt-dlp"}],
        },
        "nemotron_model": {
            "windows": [{"do": "Download the Nemotron-3 speaker model into models\\nemotron-3-diarization",
                         "cmd": f'{WIN_PY} -c "from huggingface_hub import hf_hub_download; '
                                f"hf_hub_download('{nemo_diar.REPO_ID}', '{nemo_diar.MODEL_FILENAME}', local_dir='models/nemotron-3-diarization')\""}],
            "linux": [{"do": "Download the Nemotron-3 speaker model into models/nemotron-3-diarization",
                       "cmd": f'{LNX_PY} -c "from huggingface_hub import hf_hub_download; '
                              f"hf_hub_download('{nemo_diar.REPO_ID}', '{nemo_diar.MODEL_FILENAME}', local_dir='models/nemotron-3-diarization')\""}],
        },
        "disk": {
            "windows": [{"do": "Free up space, or move the app folder to a bigger drive. Old meetings can be deleted from the meeting list."}],
            "linux": [{"do": "Free up space, or move the app folder to a bigger disk. Old meetings can be deleted from the meeting list."}],
        },
    }


def _evaluate(cfg: dict) -> dict:
    """Run every setup check. Also what the installer re-runs after each step."""
    import platform
    import shutil as sh
    checks = []
    fixes = _fixes(cfg)
    osname = "windows" if os.name == "nt" else "linux"

    def add(cid, name, ok, detail, hint="", req="always"):
        # req: "always" = needed for any engine; "local" = only for the local
        # engine (+ the Re-detect speakers button); "optional" = nice to have
        # fix: BOTH OSes — the page lets you switch tabs to see either
        # auto: the installer can fix it unattended (see installer.py); otherwise manual steps only
        checks.append({"id": cid, "name": name, "ok": bool(ok), "detail": detail,
                       "hint": hint, "req": req, "auto": cid in installer_mod.STEP_IDS,
                       "fix": fixes.get(cid, {"windows": [], "linux": []})})

    pv = platform.python_version()
    add("python", "Python 3.10+", tuple(map(int, pv.split(".")[:2])) >= (3, 10), pv)
    add("core", "Web server packages", True,
        f"fastapi {__import__('fastapi').__version__}")

    ff = ffmpeg_tools.resolve_ffmpeg()
    add("ffmpeg", "ffmpeg (audio converter)", ff.path,
        f"{ff.source}: {ff.path}" if ff.path else
        "not found — required for every engine (pip install -r requirements.txt bundles it)")

    free_gb = sh.disk_usage(str(DATA_DIR)).free / 1e9
    add("disk", "Disk space", free_gb > 5, f"{free_gb:.0f} GB free",
        "" if free_gb > 5 else "Less than 5 GB free — recordings may fail to save")

    for pkg, cid, label in [("faster_whisper", "faster_whisper", "faster-whisper (Whisper engine)"),
                            ("ctranslate2", "ctranslate2", "CTranslate2 (inference runtime)")]:
        try:
            mod = __import__(pkg)
            add(cid, label, True, getattr(mod, "__version__", "installed"), req="local")
        except ImportError:
            add(cid, label, False, "not installed", req="local")

    try:
        mod = __import__("sherpa_onnx")
        add("sherpa_onnx", "sherpa-onnx (speaker detection)", True,
            getattr(mod, "__version__", "installed"),
            "Also used by 'Re-detect speakers' on cloud meetings", req="local")
    except ImportError:
        add("sherpa_onnx", "sherpa-onnx (speaker detection)", False, "not installed", req="local")

    if cfg.get("device") == "cpu":
        add("cuda", "NVIDIA GPU (CUDA)", True, "CPU-only mode selected — GPU not used",
            req="optional")
    else:
        try:
            pipeline._setup_cuda_dlls()
            import ctranslate2
            n = ctranslate2.get_cuda_device_count()
            add("cuda", "NVIDIA GPU (CUDA)", n > 0,
                f"{n} CUDA device(s) — local transcription runs on GPU" if n
                else "no CUDA device — local engine will use CPU",
                "" if n else "Only NVIDIA GPUs accelerate; AMD/Intel run in CPU mode. "
                             "The app still works — pick a smaller Whisper model above.",
                req="optional")
        except Exception as e:
            add("cuda", "NVIDIA GPU (CUDA)", False, str(e)[:120],
                "Local engine will use CPU — pick a smaller Whisper model above", req="optional")

    wm = cfg.get("whisper_model", "large-v3")
    whisper_cache = installer_mod.whisper_cache_dir(wm)
    add("whisper_model", f"Whisper model '{wm}'", whisper_cache.exists(),
        str(whisper_cache) if whisper_cache.exists() else "not downloaded yet",
        "" if whisper_cache.exists() else "Downloads automatically on first local transcription",
        req="local")

    add("seg_model", "Speaker segmentation model", pipeline.SEG_MODEL.exists(),
        pipeline.SEG_MODEL.name if pipeline.SEG_MODEL.exists() else "missing from models/",
        req="local")
    add("emb_model", "Speaker embedding model", pipeline.EMB_MODEL.exists(),
        pipeline.EMB_MODEL.name if pipeline.EMB_MODEL.exists() else "missing from models/",
        req="local")

    # Optional Nemotron-3 speaker detection. Never "required", even while chosen:
    # a missing install just falls back to the standard diarizer, so it must not
    # lock Home. Settings -> Speakers offers the install.
    nemo_ok = nemo_diar.is_installed()
    add("nemo_toolkit", "NeMo + PyTorch (Nemotron-3 speakers)", nemo_ok,
        "installed" if nemo_ok else "not installed",
        "Optional, experimental — only needed for Nemotron-3 speaker detection", req="optional")
    add("nemotron_model", "Nemotron-3 speaker model", nemo_diar.model_present(),
        nemo_diar.MODEL_FILENAME if nemo_diar.model_present() else "not downloaded",
        req="optional")

    # Optional YouTube links. Same rule as Nemotron: never "required".
    yt_ok = linkfetch.available()
    add("yt_dlp", "YouTube downloader (yt-dlp)", yt_ok,
        (linkfetch.version() or "installed") if yt_ok else "not installed",
        "Optional: only needed for the YouTube links setting", req="optional")

    om = summarizer.ollama_model()
    add("ollama", "Ollama (better summaries)", om, om or "not running",
        "" if om else "Optional — without it you still get a built-in extractive summary",
        req="optional")

    add("gemini_key", "Google Gemini API key", bool(cfg.get("gemini_api_key")),
        "configured" if cfg.get("gemini_api_key") else "not set", req="gemini")

    cuda = next(c for c in checks if c["id"] == "cuda")
    return {
        "checks": checks,
        "engine": cfg["engine"],
        "os": osname,
        "os_detail": f"{platform.system()} {platform.release()}",
        "compute": "gpu" if cuda["ok"] and cfg.get("device") != "cpu" else "cpu",
        "diarizer_gate": _diarizer_gate(),
    }


_gate_cache = None


def _diarizer_gate() -> dict:
    """Soft-gate verdict for Nemotron-3 on this PC (cached: the GPU does not change)."""
    global _gate_cache
    if _gate_cache is None:
        import sys
        gpu = nemo_diar.gpu_info()
        osname = "mac" if sys.platform == "darwin" else ("windows" if os.name == "nt" else "linux")
        _gate_cache = nemo_diar.gate(gpu["count"], gpu["vram_mb"], osname, gpu["driver"])
    return _gate_cache


# ---------------------------------------------------------------- updates

def _meeting_busy() -> bool:
    return jobs.unfinished_tasks > 0 or bool(live_status)


app_updater = updater_mod.Updater(BASE_DIR, busy=_meeting_busy)


@app.get("/api/version")
def api_version():
    """{version, install_type: git | zip-git | zip, can_update, reason}; reason says why not, in plain words."""
    return {**app_updater.version_info(), "version": __version__}


@app.get("/api/update/check")
def update_check(force: int = 0):
    """{current, latest, available, notes, url, checked_at, error?}. Cached for 6 hours; ?force=1 asks GitHub again.
    A network failure is an answer (error: "network"), never an HTTP error."""
    return app_updater.check(force=bool(force))


@app.post("/api/update/apply")
def update_apply():
    """Start the update in the background (409 with a reason when refused or already running)."""
    try:
        return app_updater.apply()
    except updater_mod.Refused as e:
        raise HTTPException(409, str(e))


@app.get("/api/update/status")
def update_status():
    return app_updater.status()


# One-click setup. The installer re-runs the checks after each step, so it is
# built around _evaluate; tests swap this for an Installer with fake steps.
setup_installer = installer_mod.Installer(
    steps=installer_mod.default_steps(),
    evaluate=lambda: _evaluate(config.load()),
)


@app.get("/api/setup/install")
def setup_install_state():
    """Cheap per-item install state, for polling: {running, order, items:{id:{state,message,progress}}}.
    state is pending | running | done | failed. The same object is embedded in GET /api/setup."""
    return setup_installer.snapshot()


@app.post("/api/setup/install")
def setup_install(body: dict = None):
    """Start the unattended install steps in ONE background thread.
    Body: {"ids": [...]} to pick items; omitted = every missing item the current engine needs.
    A request while a run is active is merged into it (started=false, merged=true)."""
    ids = (body or {}).get("ids")
    if ids is not None and not (isinstance(ids, list) and all(isinstance(i, str) for i in ids)):
        raise HTTPException(400, "ids must be a list of check ids")
    try:
        return setup_installer.start(ids)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/setup")
def setup_check():
    cfg = config.load()
    out = _evaluate(cfg)
    out.update({
        "install": setup_installer.snapshot(),
        "python_exe": _py(""),
        "app_dir": str(BASE_DIR.resolve()),
        "architecture": {
            "local": [
                {"stage": "1 · Audio preparation", "tech": "ffmpeg",
                 "desc": "Any format → 16 kHz mono WAV. A high-pass filter removes room rumble and speech normalization boosts quiet or far-from-mic voices."},
                {"stage": "2 · Speech-to-text", "tech": "Whisper large-v3 (faster-whisper / CTranslate2, GPU)",
                 "desc": "OpenAI's multilingual speech model — strongest open model for Malay + English, handles code-switching. Voice-activity detection skips silence."},
                {"stage": "3 · Speaker detection (diarization)", "tech": "pyannote segmentation 3.0 + NeMo TitaNet-Large (sherpa-onnx)",
                 "desc": "Finds who-spoke-when: segmentation splits speech turns, a voice-embedding model fingerprints each turn, clustering groups turns by voice. Setting the real speaker count beats auto-detect."},
                {"stage": "4 · Merge", "tech": "overlap matching",
                 "desc": "Each transcript sentence gets the speaker whose talking time overlaps it most."},
                {"stage": "5 · Summary", "tech": "Ollama LLM (if installed) or built-in extractive",
                 "desc": "Key points, decisions and action items in the meeting's own language."},
            ],
            "gemini": [
                {"stage": "1 · Audio preparation", "tech": "ffmpeg",
                 "desc": "Compress to mono 48 kbps MP3, then split into ~5 minute chunks cut at natural silence points (so no word is sliced in half)."},
                {"stage": "2 · Upload", "tech": "Google Files API",
                 "desc": "Each chunk is uploaded to Google's servers (audio leaves your laptop!). Google keeps uploaded files ~48 hours."},
                {"stage": "3 · Transcribe (text only)", "tech": config.load()["gemini_model"],
                 "desc": "Each chunk is transcribed separately. Gemini is deliberately NOT asked for timestamps: measured against ground truth its clock ran 1.66x fast on one chunk, returned all-zeros on another, and emitted invalid JSON on a third. Its text and ordering, however, are reliable."},
                {"stage": "4 · Timing", "tech": "Silero VAD + proportional layout, CPU",
                 "desc": "Voice-activity detection finds exactly where speech occurs locally, and Gemini's text is laid across those regions in proportion to its length, skipping silence. Measured accuracy: median 1.8s error, max 7.4s (vs ~400s using Gemini's own timestamps)."},
                {"stage": "5 · Speaker detection", "tech": "local diarization (sherpa-onnx), CPU",
                 "desc": "Gemini labels speakers per request, so labels from different chunks are not the same people. Local diarization relabels the whole file consistently. If the local models are absent, Gemini's per-chunk labels are used instead."},
                {"stage": "6 · Summary", "tech": "Ollama LLM (if installed) or built-in extractive",
                 "desc": "Same as local mode."},
            ],
            "limitations": [
                "Overlapping speech: when two people talk at the SAME time, the microphone captures one mixed sound wave — the transcriber hears it as a single stream, so overlapped words are attributed to the dominant voice. No current system fully separates them from a single-mic recording.",
                "Auto speaker count tends to over-split on echoey room recordings — always set the real number of speakers if you know it.",
                "Very distant/quiet voices are boosted by speech normalization but may still be missed if inaudible to a human listener too.",
                "Cloud engine timing is reconstructed locally, not reported by Gemini (whose timestamps proved unusable). Measured median error is ~2s and worst ~7s, so a line may highlight a moment early or late. The local Whisper engine's timestamps come straight from the model and are exact.",
            ],
        },
    })
    return out


@app.post("/api/meetings")
async def upload(file: UploadFile = File(...), title: str = Form(""),
                 language: str = Form(""), num_speakers: int = Form(0)):
    mid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    d = DATA_DIR / mid
    d.mkdir()
    safe_name = "audio" + Path(file.filename or "audio.mp3").suffix.lower()
    with open(d / safe_name, "wb") as f:
        shutil.copyfileobj(file.file, f)
    meta = {
        "id": mid,
        "title": title.strip() or Path(file.filename or "Meeting").stem,
        "created": datetime.now().isoformat(timespec="seconds"),
        "audio_file": safe_name,
        "language": language if language in ("ms", "en") else "",
        "num_speakers": num_speakers if num_speakers > 0 else 0,
        "status": "queued", "progress": 0,
        "speaker_names": {},
        "engine": config.load()["engine"],
    }
    write_meta(mid, meta)
    jobs.put(("full", mid, None))
    return {"id": mid}


@app.post("/api/meetings/link")
def add_link(body: dict):
    """A meeting from a YouTube link: {url, title?, language?, num_speakers?}.
    Only when the "YouTube links" setting is on. The download itself runs in the
    worker, so this returns at once and the row shows the progress.
    Refusals carry a code in `detail`: link_off (403), link_bad_link (400), link_not_installed (409)."""
    if not config.load().get("youtube_links"):
        raise HTTPException(403, "link_off")
    url = linkfetch.video_url(body.get("url"))
    if not url:
        raise HTTPException(400, "link_bad_link")
    if not linkfetch.available():
        raise HTTPException(409, "link_not_installed")
    title = body.get("title") if isinstance(body.get("title"), str) else ""
    language = body.get("language")
    n = body.get("num_speakers")
    n = n if isinstance(n, int) and not isinstance(n, bool) and n > 0 else 0
    mid = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    (DATA_DIR / mid).mkdir()
    meta = {
        "id": mid,
        "title": title.strip() or linkfetch.PLACEHOLDER_TITLE,
        "created": datetime.now().isoformat(timespec="seconds"),
        "audio_file": "",
        "source_url": url,
        "language": language if language in ("ms", "en") else "",
        "num_speakers": n,
        "status": "queued", "progress": 0,
        "speaker_names": {},
        "engine": config.load()["engine"],
    }
    write_meta(mid, meta)
    jobs.put(("full", mid, None))
    return {"id": mid}


def _quick_summary(d: Path) -> str:
    """The gist shown on a schedule row; empty when there is no (readable) summary.md."""
    try:
        return summarizer.quick_summary((d / "summary.md").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""


@app.get("/api/meetings")
def list_meetings():
    out = []
    for d in sorted(DATA_DIR.iterdir(), reverse=True):
        if (d / "meta.json").exists():
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            live = live_status.get(m["id"])
            if live:
                m.update(status=live["stage"], progress=live["progress"])
            m["quick_summary"] = _quick_summary(d)
            out.append(m)
    return out


@app.get("/api/search")
def search_meetings(q: str = ""):
    """Everything said in every finished meeting that contains `q` (ignoring
    case): {query, total, meetings: {id: {total, hits: [{index, start, speaker,
    text}]}}}. Each meeting carries its first few hits and the full count."""
    return search_mod.find(DATA_DIR, q)


@app.get("/api/meetings/{mid}/live")
def get_live_lines(mid: str, after: int = 0):
    """While a recording is being transcribed: the lines produced so far, from
    line number `after` on. {status, progress, total, lines: [{start, text}]}.
    Speakers are not known yet. Empty once the job has finished."""
    meta = read_meta(mid)
    live = live_status.get(mid)
    if live:
        meta.update(status=live["stage"], progress=live["progress"])
    lines = live_lines.get(mid) or []
    after = max(0, after)
    return {"status": meta.get("status"), "progress": meta.get("progress", 0),
            "total": len(lines), "lines": lines[after:]}


@app.get("/api/meetings/{mid}")
def get_meeting(mid: str):
    meta = read_meta(mid)
    live = live_status.get(mid)
    if live:
        meta.update(status=live["stage"], progress=live["progress"])
    summary_p = DATA_DIR / mid / "summary.md"
    return {
        "meta": meta,
        "segments": read_transcript(mid),
        "summary": summary_p.read_text(encoding="utf-8") if summary_p.exists() else "",
        # True while the untouched transcript is kept beside a corrected one
        "corrected": corrections.has_backup(DATA_DIR / mid),
        "known_names": known_speaker_names(),
    }


def known_speaker_names() -> list[str]:
    """Every name the user has given a speaker, in any meeting: offered as
    suggestions when naming a speaker, so a regular is typed once."""
    names = set()
    for d in DATA_DIR.iterdir():
        try:
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        names.update(str(v).strip() for v in (m.get("speaker_names") or {}).values() if str(v).strip())
    return sorted(names, key=str.casefold)


@app.get("/api/meetings/{mid}/audio")
def get_audio(mid: str):
    meta = read_meta(mid)
    if not _has_audio(DATA_DIR / mid, meta):   # a link that has not downloaded yet
        raise HTTPException(404, "no audio yet")
    return FileResponse(DATA_DIR / mid / meta["audio_file"])


@app.patch("/api/meetings/{mid}")
def patch_meeting(mid: str, body: dict):
    with meta_lock(mid):
        meta = read_meta(mid)
        if "title" in body:
            meta["title"] = str(body["title"]).strip() or meta["title"]
        if "speaker_names" in body:
            meta.setdefault("speaker_names", {}).update(
                {str(k): str(v).strip() for k, v in body["speaker_names"].items() if str(v).strip()})
            if meta.get("status") == "done":
                # the built-in summary prints names in its speaking-time list
                _refresh_summary(mid, meta, read_transcript(mid), names_only=True)
        _write_meta_unlocked(mid, meta)
    return meta


# ---------------------------------------------------------------- corrections
# Fixing a finished transcript by hand. See corrections.py for the rules and
# for where the untouched original is kept.

def _refresh_summary(mid: str, meta: dict, segments: list, names_only: bool = False) -> str:
    """After a correction. The built-in summary is instant, so it is rewritten
    on the spot. An AI-written one takes minutes: it is kept and marked stale,
    and the Summary tab offers to write it again. Caller holds meta_lock(mid)."""
    p = DATA_DIR / mid / "summary.md"
    if meta.get("summary_engine") == "extractive" and segments:
        text = summarizer.extractive(segments, meta.get("speaker_names", {}))
        p.write_text(text, encoding="utf-8")
        meta.pop("summary_stale", None)
        return text
    if not names_only:
        meta["summary_stale"] = True
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _correct(mid: str, change):
    """Run change(segments, meta) -> (changed indexes, removed index or None)
    on a finished meeting and save the result. 409 while the meeting is being
    processed, 400 when the change does not apply."""
    d = meeting_dir(mid)
    with meta_lock(mid):
        meta = read_meta(mid)
        if meta.get("status") != "done" or mid in live_status:
            raise HTTPException(409, "this meeting is being processed")
        segments = read_transcript(mid)
        before = json.dumps(segments, ensure_ascii=False)
        names_before = dict(meta.get("speaker_names") or {})
        meta.setdefault("speaker_names", {})
        try:
            changed, removed = change(segments, meta)
        except corrections.CorrectionError as e:
            raise HTTPException(400, str(e))
        summary = None
        if changed or removed is not None:
            corrections.backup_once(d, json.loads(before), names_before)
            write_transcript(mid, segments)
            meta["num_speakers_found"] = len(corrections.speakers_in(segments))
            summary = _refresh_summary(mid, meta, segments)
            _write_meta_unlocked(mid, meta)
        if summary is None:
            sp = d / "summary.md"
            summary = sp.read_text(encoding="utf-8") if sp.exists() else ""
        return {
            "changed": {str(i): segments[i] for i in changed},
            "removed": removed,
            "meta": meta,
            "summary": summary,
            "corrected": corrections.has_backup(d),
        }


@app.patch("/api/meetings/{mid}/segments/{index}")
def correct_segment(mid: str, index: int, body: dict):
    """Correct one line. Body: {start, text?} | {start, restore: true} |
    {start, speaker: N | "new", turn?: bool}. `start` is the line's start time
    as the browser has it, so a stale page cannot edit the wrong line."""
    def change(segments, meta):
        seg = corrections.locate(segments, index, body.get("start"))
        changed = []
        if body.get("restore"):
            if corrections.restore_text(seg):
                changed.append(index)
        elif "text" in body:
            if corrections.set_text(seg, body["text"]):
                changed.append(index)
        if "speaker" in body:
            changed += corrections.set_speaker(segments, index, body["speaker"], bool(body.get("turn")))
        return sorted(set(changed)), None
    return _correct(mid, change)


@app.delete("/api/meetings/{mid}/segments/{index}")
def delete_segment(mid: str, index: int, start: float | None = None):
    """Remove one line (a line Whisper made up over silence, for example)."""
    def change(segments, meta):
        corrections.locate(segments, index, start)
        del segments[index]
        return [], index
    return _correct(mid, change)


@app.post("/api/meetings/{mid}/speakers/merge")
def merge_speakers(mid: str, body: dict):
    """Body: {"from": N, "into": M}. Everything N said becomes M's."""
    def change(segments, meta):
        return corrections.merge_speakers(
            segments, meta["speaker_names"], body.get("from"), body.get("into")), None
    return _correct(mid, change)


@app.post("/api/meetings/{mid}/corrections/discard")
def discard_corrections(mid: str):
    """Put the transcript back as the pipeline wrote it and forget every
    correction (text, speakers, deleted lines, merges)."""
    d = meeting_dir(mid)
    with meta_lock(mid):
        meta = read_meta(mid)
        if meta.get("status") != "done" or mid in live_status:
            raise HTTPException(409, "this meeting is being processed")
        if not corrections.has_backup(d):
            raise HTTPException(400, "nothing to discard")
        try:
            original = corrections.read_backup(d)
        except (OSError, ValueError) as e:
            raise HTTPException(500, f"the saved original cannot be read: {e}")
        write_transcript(mid, original["segments"])
        meta["speaker_names"] = original["speaker_names"]
        meta["num_speakers_found"] = len(corrections.speakers_in(original["segments"]))
        _refresh_summary(mid, meta, original["segments"])
        _write_meta_unlocked(mid, meta)
        corrections.drop_backup(d)
    return get_meeting(mid)


@app.post("/api/meetings/{mid}/retranscribe")
def retranscribe(mid: str):
    """Re-run the whole pipeline on the stored audio, using the engine that is
    configured now (e.g. after switching local <-> cloud)."""
    with meta_lock(mid):
        meta = read_meta(mid)
        meta["engine"] = config.load()["engine"]
        meta["status"], meta["progress"] = "queued", 0
        _write_meta_unlocked(mid, meta)
    jobs.put(("full", mid, None))
    return {"ok": True, "engine": meta["engine"]}


@app.post("/api/meetings/{mid}/rediarize")
def rediarize(mid: str, num_speakers: int = 0):
    """Re-run speaker detection only (keeps the transcript text)."""
    if not read_transcript(mid):
        raise HTTPException(400, "no transcript yet")
    with meta_lock(mid):
        meta = read_meta(mid)
        meta["status"], meta["progress"] = "queued", 0
        _write_meta_unlocked(mid, meta)
    jobs.put(("rediarize", mid, num_speakers if num_speakers > 0 else None))
    return {"ok": True}


@app.post("/api/meetings/{mid}/resummarize")
def resummarize(mid: str):
    meta = read_meta(mid)
    segments = read_transcript(mid)
    if not segments:
        raise HTTPException(400, "no transcript yet")
    summary, engine = summarizer.summarize(segments, meta.get("speaker_names", {}))
    (DATA_DIR / mid / "summary.md").write_text(summary, encoding="utf-8")
    with meta_lock(mid):
        meta = read_meta(mid)  # re-read: names may have changed during the summary
        meta["summary_engine"] = engine
        meta.pop("summary_stale", None)
        _write_meta_unlocked(mid, meta)
    return {"summary": summary, "engine": engine}


@app.delete("/api/meetings/{mid}")
def delete_meeting(mid: str):
    shutil.rmtree(meeting_dir(mid))
    return {"ok": True}


def _fmt_ts(sec: float, srt=False) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    if srt:
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


@app.get("/api/meetings/{mid}/export")
def export(mid: str, format: str = "txt"):
    meta = read_meta(mid)
    segs = read_transcript(mid)
    summary_p = DATA_DIR / mid / "summary.md"
    summary = summary_p.read_text(encoding="utf-8") if summary_p.exists() else ""
    title = meta["title"]

    if format == "srt":
        lines = []
        for i, s in enumerate(segs, 1):
            lines += [str(i), f"{_fmt_ts(s['start'], True)} --> {_fmt_ts(timing.spoken_end(s), True)}",
                      f"[{speaker_label(meta, s['speaker'])}] {s['text']}", ""]
        body, ext = "\n".join(lines), "srt"
    elif format == "md":
        lines = [f"# {title}", f"_{meta['created']} · {meta.get('duration', 0) / 60:.0f} min_",
                 "", "## Summary", summary, "", "## Transcript", ""]
        for s in segs:
            lines.append(f"**[{_fmt_ts(s['start'])}] {speaker_label(meta, s['speaker'])}:** {s['text']}")
            lines.append("")
        body, ext = "\n".join(lines), "md"
    else:
        lines = [title, meta["created"], "=" * 40, ""]
        for s in segs:
            lines.append(f"[{_fmt_ts(s['start'])}] {speaker_label(meta, s['speaker'])}: {s['text']}")
        body, ext = "\n".join(lines), "txt"

    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in title)[:60]
    return PlainTextResponse(body, headers={
        "Content-Disposition": f'attachment; filename="{safe}.{ext}"'})


if __name__ == "__main__":
    # HOST=0.0.0.0 to expose it on a LAN / Linux server
    import port as port_mod
    host = os.environ.get("HOST", "127.0.0.1")
    wanted = int(os.environ.get("PORT") or port_mod.DEFAULT_PORT)
    port = port_mod.pick(host, wanted)   # taken (another program, or NoteRecall already running)? next one up
    if port != wanted:
        print(f"Port {wanted} is in use; using {port} instead.")
    print(f"NoteRecall -> http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
