"""Audio -> transcript pipeline: ffmpeg convert, faster-whisper transcribe,
sherpa-onnx speaker diarization, merge."""

import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

import ffmpeg_tools

BASE_DIR = Path(__file__).parent
MODELS_DIR = BASE_DIR / "models"
FFMPEG = ffmpeg_tools.ffmpeg_exe()

SEG_MODEL = MODELS_DIR / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"
EMB_MODEL = MODELS_DIR / "nemo_en_titanet_large.onnx"

# Thread cap for CPU work (diarization here, Whisper in get_whisper).
# Do NOT raise this. Measured on 95s of audio, large-v3 int8, 20-thread CPU:
#   8 threads -> 38.5s (2.5x realtime)   <- best
#  16 threads -> 134.1s (0.7x realtime)  <- 3.5x SLOWER
#  20 threads -> 187.7s (0.5x realtime)  <- 5x slower
# More threads oversubscribe the P/E-core mix and thrash; it also keeps the
# machine usable while a job runs.
CPU_THREADS = min(8, os.cpu_count() or 8)
DIAR_THREADS = CPU_THREADS
# cosine-distance threshold for auto speaker clustering. Tuned on real meeting
# audio: lower values over-split one voice into many "speakers". If the auto
# count still looks too high, prefer setting the speaker count explicitly.
DIAR_THRESHOLD = 1.0

_whisper_model = None
_whisper_device = None
_whisper_key = None  # (model_name, device) the cache was loaded with


def _setup_cuda_dlls():
    """Make the pip-installed cuBLAS/cuDNN libraries visible to ctranslate2.

    Windows and Linux need completely different treatment:
      * Windows: register the DLL directory (os.add_dll_directory doesn't exist
        on Linux, so this must never run there).
      * Linux: the dynamic loader reads LD_LIBRARY_PATH at process start, so
        setting it now would be ignored — preload the .so files instead."""
    try:
        import sysconfig
        nvidia = Path(sysconfig.get_paths()["purelib"]) / "nvidia"
        if not nvidia.is_dir():
            return
        if os.name == "nt":
            for sub in ("cublas", "cudnn"):
                bindir = nvidia / sub / "bin"
                if bindir.is_dir():
                    os.add_dll_directory(str(bindir))
                    os.environ["PATH"] = str(bindir) + os.pathsep + os.environ.get("PATH", "")
        else:
            import ctypes
            import glob
            for sub in ("cublas", "cudnn"):  # cublas first: cudnn depends on it
                for so in sorted(glob.glob(str(nvidia / sub / "lib" / "*.so*"))):
                    try:
                        ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass
    except Exception as e:
        print(f"[pipeline] CUDA library setup skipped: {e}", flush=True)


def get_whisper():
    """Load whisper per config: device auto (NVIDIA GPU -> CPU fallback) or cpu.

    Reloads automatically when the configured model/device changes."""
    global _whisper_model, _whisper_device, _whisper_key
    import config as appconfig
    cfg = appconfig.load()
    model_name = cfg.get("whisper_model") or "large-v3"
    device = cfg.get("device") or "auto"
    key = (model_name, device)
    if _whisper_model is not None and _whisper_key == key:
        return _whisper_model, _whisper_device

    _setup_cuda_dlls()
    from faster_whisper import WhisperModel

    _whisper_model = None
    if device != "cpu":
        try:
            m = WhisperModel(model_name, device="cuda", compute_type="float16")
            # force weight load / cuda init so failure happens here, not mid-job
            m.transcribe(np.zeros(16000, dtype=np.float32), language="en")
            _whisper_model, _whisper_device = m, f"cuda ({model_name})"
        except Exception as e:
            print(f"[pipeline] CUDA unavailable ({e}); falling back to CPU", flush=True)
    if _whisper_model is None:
        # Never silently swap the model on CPU. Measured on 95s of real
        # Malay/English meeting audio (20-core CPU, int8): large-v3 runs at
        # 2.5x realtime vs base at 5.5x — barely faster — while the smaller
        # models TRANSLATE the English into Malay instead of transcribing it.
        # A quiet downgrade would hand back wrong-language text; make the user
        # choose a smaller model deliberately in Setup instead.
        m = WhisperModel(model_name, device="cpu", compute_type="int8",
                         cpu_threads=CPU_THREADS)
        _whisper_model, _whisper_device = m, f"cpu ({model_name})"
    _whisper_key = key
    return _whisper_model, _whisper_device


def convert_to_wav(src: Path, dst: Path):
    """Convert any audio/video file to 16 kHz mono PCM wav.

    highpass removes room rumble; speechnorm boosts quiet/distant voices so
    far-from-mic speakers are still detected."""
    cmd = [FFMPEG, "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
           "-af", "highpass=f=70,speechnorm=e=12:r=0.0001:l=1",
           "-vn", "-f", "wav", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-800:]}")


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe(wav_path: Path, language: str | None, progress_cb=None):
    """Run whisper. Returns (segments list, detected language, duration)."""
    model, _ = get_whisper()
    segments, info = model.transcribe(
        str(wav_path),
        language=language or None,
        beam_size=5,
        vad_filter=True,
        # threshold below default 0.5 so quiet / far-from-mic speech still passes
        vad_parameters={"min_silence_duration_ms": 700, "threshold": 0.35},
        condition_on_previous_text=False,
    )
    out = []
    duration = info.duration or 1.0
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        out.append({"start": round(seg.start, 2), "end": round(seg.end, 2),
                    "text": text, "speaker": -1})
        if progress_cb:
            progress_cb(min(seg.end / duration, 1.0))
    return out, info.language, duration


def diarize(audio: np.ndarray, num_speakers: int | None, progress_cb=None):
    """Return list of (start, end, speaker_int) turns."""
    import sherpa_onnx

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(SEG_MODEL)),
            num_threads=DIAR_THREADS,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(EMB_MODEL),
            num_threads=DIAR_THREADS,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers or -1,
            threshold=DIAR_THRESHOLD,
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    sd = sherpa_onnx.OfflineSpeakerDiarization(config)

    def cb(done, total, arg=None):
        if progress_cb:
            progress_cb(done / max(total, 1))
        return 0

    result = sd.process(audio, callback=cb).sort_by_start_time()
    return [(r.start, r.end, r.speaker) for r in result]


def assign_speakers(segments, turns):
    """Give each transcript segment the speaker with the largest time overlap."""
    for seg in segments:
        best, best_ov = -1, 0.0
        for ts, te, spk in turns:
            ov = min(seg["end"], te) - max(seg["start"], ts)
            if ov > best_ov:
                best_ov, best = ov, spk
        if best == -1 and turns:
            # no overlap (e.g. VAD mismatch): use nearest turn by midpoint
            mid = (seg["start"] + seg["end"]) / 2
            best = min(turns, key=lambda t: abs((t[0] + t[1]) / 2 - mid))[2]
        seg["speaker"] = int(best)
    return segments


def compact_speakers(segments: list) -> int:
    """Renumber speakers 0..n-1 in order of first speaking.

    Clustering hands back arbitrary cluster ids, so without this a meeting
    with 5 voices can show up as "Speaker 11" / "Speaker 12"."""
    order: dict[int, int] = {}
    for s in segments:
        spk = s.get("speaker", -1)
        if spk >= 0 and spk not in order:
            order[spk] = len(order)
    for s in segments:
        spk = s.get("speaker", -1)
        s["speaker"] = order.get(spk, -1) if spk >= 0 else -1
    return len(order)


def run_job(audio_path: Path, work_dir: Path, language: str | None,
            num_speakers: int | None, status_cb):
    """Full pipeline. status_cb(stage, progress_0_100).

    Engine is chosen from config.json: "local" (Whisper + diarization on this
    PC) or "gemini" (Google API does transcription + speakers in one pass)."""
    import config
    cfg = config.load()
    if cfg.get("engine") == "gemini":
        import engines
        cfg = dict(cfg, num_speakers=num_speakers)  # used by local diarization
        return engines.transcribe_gemini(audio_path, work_dir, language,
                                         cfg, FFMPEG, status_cb)

    wav = work_dir / "audio16k.wav"
    status_cb("converting", 2)
    convert_to_wav(audio_path, wav)

    status_cb("transcribing", 5)
    segments, lang, duration = transcribe(
        wav, language, lambda f: status_cb("transcribing", 5 + f * 60))

    status_cb("diarizing", 66)
    audio = load_wav(wav)
    try:
        turns = diarize(audio, num_speakers,
                        lambda f: status_cb("diarizing", 66 + f * 28))
        segments = assign_speakers(segments, turns)
        n_speakers = len({s for _, _, s in turns}) if turns else 0
    except Exception as e:
        print(f"[pipeline] diarization failed: {e}", flush=True)
        n_speakers = 0

    wav.unlink(missing_ok=True)
    status_cb("summarizing", 95)
    return {"segments": segments, "language": lang,
            "duration": round(duration, 1), "num_speakers": n_speakers}


def rediarize_job(audio_path: Path, work_dir: Path, segments: list,
                  num_speakers: int | None, status_cb):
    """Re-run speaker detection on an existing transcript (text unchanged)."""
    wav = work_dir / "audio16k.wav"
    status_cb("converting", 5)
    convert_to_wav(audio_path, wav)
    status_cb("diarizing", 10)
    audio = load_wav(wav)
    turns = diarize(audio, num_speakers,
                    lambda f: status_cb("diarizing", 10 + f * 85))
    for s in segments:
        s["speaker"] = -1
    segments = assign_speakers(segments, turns)
    wav.unlink(missing_ok=True)
    status_cb("summarizing", 95)
    n_speakers = len({s for _, _, s in turns}) if turns else 0
    return {"segments": segments, "num_speakers": n_speakers}
