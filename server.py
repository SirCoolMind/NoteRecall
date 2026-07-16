"""Local meeting transcription app — FastAPI server.

Run:  .venv\\Scripts\\python.exe server.py   then open http://localhost:8756
"""

import json
import os
import queue
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

import config
import engines
import pipeline
import summarizer

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Meeting Transcriber")
jobs: "queue.Queue[str]" = queue.Queue()
live_status: dict[str, dict] = {}  # id -> {stage, progress}


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


def write_meta(mid: str, meta: dict):
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


def read_transcript(mid: str) -> list[dict]:
    p = meeting_dir(mid) / "transcript.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []


def speaker_label(meta: dict, spk: int) -> str:
    if spk < 0:
        return "?"
    return meta.get("speaker_names", {}).get(str(spk), f"Speaker {spk + 1}")


# ---------------------------------------------------------------- worker

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
            live_status[mid] = {"stage": stage, "progress": progress}
            if changed:  # progress callbacks fire very often; only hit disk on change
                write_meta(mid, meta)

        try:
            t0 = time.time()
            if kind == "rediarize":
                segments = read_transcript(mid)
                result = pipeline.rediarize_job(
                    d / meta["audio_file"], d, segments, arg or None, status)
                meta["num_speakers"] = arg or 0
                meta["speaker_names"] = {}
            else:
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
                if result.get("chunks"):
                    meta["chunks"] = result["chunks"]
            # clustering returns arbitrary ids; present them as Speaker 1..N
            n_speakers = pipeline.compact_speakers(result["segments"])
            (d / "transcript.json").write_text(
                json.dumps(result["segments"], ensure_ascii=False),
                encoding="utf-8")
            meta.update(
                num_speakers_found=n_speakers or result["num_speakers"],
                processing_seconds=round(time.time() - t0),
            )
            summary, engine = summarizer.summarize(
                result["segments"], meta.get("speaker_names", {}))
            (d / "summary.md").write_text(summary, encoding="utf-8")
            meta["summary_engine"] = engine
            meta.pop("error", None)
            status("done", 100)
        except Exception as e:
            import traceback
            traceback.print_exc()
            meta["error"] = str(e)
            status("error", 0)
        finally:
            live_status.pop(mid, None)
            jobs.task_done()


threading.Thread(target=worker, daemon=True).start()


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


requeue_unfinished()


# ---------------------------------------------------------------- api

@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/about", response_class=HTMLResponse)
def about():
    return (BASE_DIR / "static" / "about.html").read_text(encoding="utf-8")


@app.get("/setup", response_class=HTMLResponse)
def setup_page():
    return (BASE_DIR / "static" / "setup.html").read_text(encoding="utf-8")


@app.get("/api/status")
def api_status():
    cfg = config.load()
    return {
        "device": pipeline._whisper_device or "not loaded yet",
        "ollama_model": summarizer.ollama_model(),
        "queue_size": jobs.qsize(),
        "engine": cfg["engine"],
        "gemini_model": cfg["gemini_model"],
    }


@app.get("/api/config")
def get_config():
    cfg = config.load()
    key = cfg.get("gemini_api_key", "")
    cfg["gemini_api_key_masked"] = (key[:4] + "…" + key[-4:]) if len(key) > 8 else ("set" if key else "")
    cfg.pop("gemini_api_key")
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
    # only overwrite the stored key if a new one was actually typed
    if isinstance(body.get("gemini_api_key"), str) and body["gemini_api_key"].strip():
        allowed["gemini_api_key"] = body["gemini_api_key"].strip()
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
            "windows": [{"do": "Install ffmpeg (reads and converts the audio)",
                         "cmd": "winget install -e --id Gyan.FFmpeg"},
                        {"do": "Close and reopen your terminal, then check it is on PATH",
                         "cmd": "ffmpeg -version"}],
            "linux": [{"do": "Install ffmpeg — Debian/Ubuntu", "cmd": "sudo apt install -y ffmpeg"},
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
        "disk": {
            "windows": [{"do": "Free up space, or move the app folder to a bigger drive. Old meetings can be deleted from the meeting list."}],
            "linux": [{"do": "Free up space, or move the app folder to a bigger disk. Old meetings can be deleted from the meeting list."}],
        },
    }


@app.get("/api/setup")
def setup_check():
    import platform
    import shutil as sh
    cfg = config.load()
    checks = []
    fixes = _fixes(cfg)
    osname = "windows" if os.name == "nt" else "linux"

    def add(cid, name, ok, detail, hint="", req="always"):
        # req: "always" = needed for any engine; "local" = only for the local
        # engine (+ the Re-detect speakers button); "optional" = nice to have
        # fix: BOTH OSes — the page lets you switch tabs to see either
        checks.append({"id": cid, "name": name, "ok": bool(ok), "detail": detail,
                       "hint": hint, "req": req,
                       "fix": fixes.get(cid, {"windows": [], "linux": []})})

    pv = platform.python_version()
    add("python", "Python 3.10+", tuple(map(int, pv.split(".")[:2])) >= (3, 10), pv)
    add("core", "Web server packages", True,
        f"fastapi {__import__('fastapi').__version__}")

    ff = sh.which(pipeline.FFMPEG) or (pipeline.FFMPEG if Path(pipeline.FFMPEG).exists() else None)
    add("ffmpeg", "ffmpeg (audio converter)", ff, ff or "not found — required for every engine")

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
    # honour HF_HOME / HF_HUB_CACHE — a systemd service usually sets one, and
    # hardcoding ~/.cache would report "not downloaded" for a model that is
    # sitting right there
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
        hub = Path(HF_HUB_CACHE)
    except Exception:
        hub = Path(os.environ.get("HF_HUB_CACHE")
                   or os.environ.get("HUGGINGFACE_HUB_CACHE")
                   or Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub")
    whisper_cache = hub / f"models--Systran--faster-whisper-{wm}"
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

    om = summarizer.ollama_model()
    add("ollama", "Ollama (better summaries)", om, om or "not running",
        "" if om else "Optional — without it you still get a built-in extractive summary",
        req="optional")

    add("gemini_key", "Google Gemini API key", bool(cfg.get("gemini_api_key")),
        "configured" if cfg.get("gemini_api_key") else "not set", req="gemini")

    return {
        "checks": checks,
        "engine": cfg["engine"],
        "os": osname,
        "os_detail": f"{platform.system()} {platform.release()}",
        "python_exe": _py(""),
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
    }


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


@app.get("/api/meetings")
def list_meetings():
    out = []
    for d in sorted(DATA_DIR.iterdir(), reverse=True):
        if (d / "meta.json").exists():
            m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
            live = live_status.get(m["id"])
            if live:
                m.update(status=live["stage"], progress=live["progress"])
            out.append(m)
    return out


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
    }


@app.get("/api/meetings/{mid}/audio")
def get_audio(mid: str):
    meta = read_meta(mid)
    return FileResponse(DATA_DIR / mid / meta["audio_file"])


@app.patch("/api/meetings/{mid}")
def patch_meeting(mid: str, body: dict):
    meta = read_meta(mid)
    if "title" in body:
        meta["title"] = str(body["title"]).strip() or meta["title"]
    if "speaker_names" in body:
        meta.setdefault("speaker_names", {}).update(
            {str(k): str(v).strip() for k, v in body["speaker_names"].items() if str(v).strip()})
    write_meta(mid, meta)
    return meta


@app.post("/api/meetings/{mid}/retranscribe")
def retranscribe(mid: str):
    """Re-run the whole pipeline on the stored audio, using the engine that is
    configured now (e.g. after switching local <-> cloud)."""
    meta = read_meta(mid)
    meta["engine"] = config.load()["engine"]
    meta["status"], meta["progress"] = "queued", 0
    write_meta(mid, meta)
    jobs.put(("full", mid, None))
    return {"ok": True, "engine": meta["engine"]}


@app.post("/api/meetings/{mid}/rediarize")
def rediarize(mid: str, num_speakers: int = 0):
    """Re-run speaker detection only (keeps the transcript text)."""
    meta = read_meta(mid)
    if not read_transcript(mid):
        raise HTTPException(400, "no transcript yet")
    meta["status"], meta["progress"] = "queued", 0
    write_meta(mid, meta)
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
    meta["summary_engine"] = engine
    write_meta(mid, meta)
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
            lines += [str(i), f"{_fmt_ts(s['start'], True)} --> {_fmt_ts(s['end'], True)}",
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
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8756"))
    print(f"Meeting Transcriber -> http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="warning")
