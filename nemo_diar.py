"""Optional, experimental speaker detection with NVIDIA Nemotron-3-Diarization.

Off unless config "diarizer" is "nemotron"; pipeline.diarize_labeled decides
when to call it and falls back to the standard sherpa-onnx diarizer on any
error. Needs the extra packages in requirements-nemo.txt (NeMo + PyTorch),
which Settings -> Speakers / Setup installs on request. Nothing here is
imported by the app until the toggle is on.
"""

import subprocess
from pathlib import Path

import numpy as np

BASE_DIR = Path(__file__).parent
REPO_ID = "nvidia/Nemotron-3-Diarization"
MODEL_FILENAME = "Nemotron-3-Diarization.nemo"
MODEL_DIR = BASE_DIR / "models" / "nemotron-3-diarization"
MODEL_FILE = MODEL_DIR / MODEL_FILENAME
MAX_SPEAKERS = 8           # the model's fixed output size
MIN_VRAM_MB = 4096         # below this the soft gate warns
MIN_DRIVER = 580           # the CUDA 13 PyTorch build needs this NVIDIA driver or newer

_model = None
_model_device = None


# ---------------------------------------------------------------- availability

def is_installed() -> bool:
    import importlib.util
    try:
        return (importlib.util.find_spec("torch") is not None
                and importlib.util.find_spec("nemo") is not None)
    except (ImportError, ValueError):
        return False


def model_present() -> bool:
    return MODEL_FILE.exists()


def gpu_info() -> dict:
    """{"count", "vram_mb" (largest card), "driver" (major version)}; from
    nvidia-smi, which ships with the NVIDIA driver, so this works before PyTorch
    is installed. Unknown values are None."""
    rows = []
    try:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,driver_version", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10, creationflags=flags)
        if r.returncode == 0:
            rows = [[x.strip() for x in line.split(",")] for line in r.stdout.splitlines() if line.strip()]
    except Exception:
        pass
    sizes = [int(row[0]) for row in rows if row and row[0].isdigit()]
    drivers = [int(row[1].split(".")[0]) for row in rows if len(row) > 1 and row[1].split(".")[0].isdigit()]
    return {"count": len(rows), "vram_mb": max(sizes) if sizes else None,
            "driver": min(drivers) if drivers else None}


def gate(gpu_count: int, vram_mb, os_name: str, driver=None) -> dict:
    """Soft gate: never blocks, only lists reasons this PC may struggle.
    os_name: "windows" | "linux" | "mac"."""
    reasons = []
    if os_name == "mac" or not gpu_count:
        reasons.append("no_gpu")
    else:
        if vram_mb is not None and vram_mb < MIN_VRAM_MB:
            reasons.append("low_vram")
        if driver is not None and driver < MIN_DRIVER:
            reasons.append("old_driver")
    return {"ok": not reasons, "reasons": reasons, "vram_mb": vram_mb}


# ---------------------------------------------------------------- model

def _device() -> str:
    import config
    import torch
    if config.load().get("device") != "cpu" and torch.cuda.is_available():
        return "cuda"
    return "cpu"


def _use_eager_attention_without_triton():
    """NeMo runs FlexAttention through torch.compile on CUDA, which needs Triton.
    Triton does not ship for Windows, so the first forward pass dies there. Use
    the plain (eager) FlexAttention instead: same results, a little slower."""
    import importlib.util
    if importlib.util.find_spec("triton") is not None:
        return
    from torch.nn.attention.flex_attention import flex_attention
    from nemo.collections.asr.modules import transformer_encoder_utils
    transformer_encoder_utils._flex_attention_compiled = flex_attention


def _quiet_logs():
    """NeMo and its helpers print pages of training-only notes when the model
    loads (data-loader configs, telemetry, Triton, the eager attention we chose
    on purpose). None of it matters for diarization; keep real errors only."""
    import logging
    import warnings
    for name in ("nv_one_logger", "torch.utils.flop_counter"):
        logging.getLogger(name).setLevel(logging.ERROR)
    warnings.filterwarnings("ignore", message=r"flex_attention called without torch\.compile")
    from nemo.utils import logging as nemo_logging
    nemo_logging.setLevel(logging.ERROR)
    # Two progress bars ignore diarize(verbose=False); silence just those.
    from tqdm import tqdm
    from nemo.collections.asr.models import sortformer_diar_models
    from nemo.collections.asr.parts.utils import vad_utils

    def silent(*args, **kwargs):
        kwargs["disable"] = True
        return tqdm(*args, **kwargs)
    sortformer_diar_models.tqdm = vad_utils.tqdm = silent


def get_model():
    global _model, _model_device
    _quiet_logs()
    device = _device()
    if _model is not None and _model_device == device:
        return _model
    if not model_present():
        raise RuntimeError(f"{MODEL_FILENAME} is missing from models/ — install it in Settings -> Speakers")
    _use_eager_attention_without_triton()
    from nemo.collections.asr.models import SortformerEncLabelModel
    m = SortformerEncLabelModel.restore_from(str(MODEL_FILE), map_location=device)
    m.eval()
    # Streaming settings from the model card (80 ms frames): keeps memory flat
    # on hour-long meetings instead of attending over the whole file at once.
    sm = m.sortformer_modules
    sm.chunk_len = 340
    sm.chunk_right_context = 40
    sm.fifo_len = 40
    sm.spkcache_update_period = 340   # the card says 300; NeMo raises anything below chunk_len to it anyway
    m._check_streaming_parameters()
    _model, _model_device = m, device
    return m


def is_loaded() -> bool:
    """In the app process this stays False: diarize() loads the model in a
    worker process that exits when the meeting is done."""
    return _model is not None


def unload(gpu_only: bool = False) -> bool:
    """Drop the cached model and give its graphics memory back. gpu_only: only
    when it sits on the graphics card. True if one was unloaded."""
    global _model, _model_device
    if _model is None or (gpu_only and _model_device != "cuda"):
        return False
    _model, _model_device = None, None
    import gc
    import sys
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None and torch.cuda.is_available():
        torch.cuda.empty_cache()
    return True


def parse_segments(lines) -> list:
    """NeMo returns "begin end speaker_N" strings (or tuples); -> [(start, end, n)]."""
    turns = []
    for item in lines:
        parts = item.replace(",", " ").split() if isinstance(item, str) else list(item)
        if len(parts) < 3:
            continue
        spk = str(parts[2])
        digits = "".join(ch for ch in spk if ch.isdigit())
        turns.append((float(parts[0]), float(parts[1]), int(digits) if digits else 0))
    turns.sort(key=lambda t: t[0])
    return turns


def _diarize_here(audio: np.ndarray) -> list:
    """Run the model in THIS process (the worker side of diarize()).

    The audio goes in as an array, not a file path: for paths NeMo writes a
    temp manifest and reads it in a DataLoader worker process, which breaks on
    Windows ("WinError 32 ... manifest.json"). Arrays need neither."""
    model = get_model()
    import torch
    with torch.inference_mode():
        out = model.diarize(audio=[np.ascontiguousarray(audio, dtype=np.float32)],
                            sample_rate=16000, batch_size=1, num_workers=0, verbose=False)
    return parse_segments(out[0] if out else [])


def diarize(audio: np.ndarray, num_speakers, progress_cb=None) -> list:
    """Same contract as pipeline.diarize: 16 kHz mono float audio ->
    [(start, end, speaker_int)]. num_speakers is not used: the model decides
    the count itself (up to 8).

    Runs in a separate Python process. PyTorch ships its own CUDA 13 cuDNN,
    while Whisper (ctranslate2) and sherpa-onnx load the CUDA 12 one from
    requirements-gpu.txt; in one process whichever loads second fails
    (WinError 127 / DLL init failed). A child process also hands all of its
    graphics memory back the moment it exits."""
    import json
    import sys
    import tempfile
    if progress_cb:
        progress_cb(0.0)
    with tempfile.TemporaryDirectory(prefix="nemotron-") as tmp:
        src, dst = Path(tmp) / "audio.npy", Path(tmp) / "turns.json"
        np.save(src, np.ascontiguousarray(audio, dtype=np.float32))
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run([sys.executable, str(BASE_DIR / "nemo_diar.py"), str(src), str(dst)],
                           cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", creationflags=flags)
        out = json.loads(dst.read_text(encoding="utf-8")) if dst.exists() else {}
    if "turns" in out:
        if progress_cb:
            progress_cb(1.0)
        return [tuple(t) for t in out["turns"]]
    kind, msg = out.get("error", "RuntimeError"), out.get("message", "")
    if not out:  # died without a word (crash, killed): keep the end of its output
        tail = [ln for ln in (r.stderr or r.stdout or "").splitlines() if ln.strip()][-2:]
        msg = f"the Nemotron-3 process stopped (exit code {r.returncode}): " + " | ".join(tail)
    if kind in ("ImportError", "ModuleNotFoundError"):
        raise ImportError(msg)
    raise RuntimeError(f"{kind}: {msg}")


def _worker_main(src: str, dst: str) -> int:
    """python nemo_diar.py <audio.npy> <turns.json>: diarize, write the turns
    (or the error) as JSON for the parent process."""
    import json
    try:
        turns = _diarize_here(np.load(src))
        Path(dst).write_text(json.dumps({"turns": turns}), encoding="utf-8")
        return 0
    except Exception as e:
        Path(dst).write_text(json.dumps({"error": type(e).__name__, "message": str(e)[:1000]}), encoding="utf-8")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(_worker_main(sys.argv[1], sys.argv[2]))
