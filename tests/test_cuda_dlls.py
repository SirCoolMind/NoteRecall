import os
import subprocess
import sys
from pathlib import Path

import pytest

import server

ROOT = Path(__file__).resolve().parent.parent

# The live failure: Whisper's VAD loads the pip onnxruntime first, then sherpa's
# CUDA provider fails with Error 1114 and speaker detection falls back to CPU.
SCRIPT = r"""
import sys; sys.path.insert(0, {root!r})
import numpy as np, pipeline as pl, sherpa_onnx
pl._setup_cuda_dlls()
from faster_whisper.vad import get_speech_timestamps, VadOptions
get_speech_timestamps(np.zeros(16000, dtype=np.float32), VadOptions())
sherpa_onnx.SpeakerEmbeddingExtractor(sherpa_onnx.SpeakerEmbeddingExtractorConfig(
    model=str(pl.EMB_MODEL), num_threads=1, provider="cuda"))
print("OK")
"""


def _sherpa_cuda_build():
    import importlib.util
    spec = importlib.util.find_spec("sherpa_onnx")
    return bool(spec and (Path(spec.origin).parent / "lib" / "onnxruntime_providers_cuda.dll").exists())


@pytest.mark.skipif(os.name != "nt" or not _sherpa_cuda_build(), reason="Windows + CUDA sherpa-onnx only")
def test_sherpa_cuda_still_loads_after_whisper_vad():
    r = subprocess.run([sys.executable, "-c", SCRIPT.format(root=str(ROOT))],
                       capture_output=True, text=True, timeout=300, cwd=ROOT)
    assert r.stdout.strip().endswith("OK"), r.stderr[-2000:]


class _Loop:
    def __init__(self):
        self.seen = []

    def default_exception_handler(self, context):
        self.seen.append(context)


def test_connection_resets_are_dropped_other_errors_kept():
    loop = _Loop()
    server._quiet_connection_resets(loop, {"exception": ConnectionResetError(10054, "reset")})
    assert loop.seen == []
    server._quiet_connection_resets(loop, {"exception": ValueError("boom")})
    assert len(loop.seen) == 1
