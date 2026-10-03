"""Locate ffmpeg and measure audio duration with it (no ffprobe needed).

Resolution order: FFMPEG_EXE env -> ffmpeg on PATH -> binary bundled by the
imageio-ffmpeg dependency (which ships ffmpeg only, no ffprobe).
"""

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple, Optional


class FfmpegLocation(NamedTuple):
    path: Optional[str]
    source: str  # "env" | "PATH" | "bundled" | "none"


def resolve_ffmpeg() -> FfmpegLocation:
    env = os.environ.get("FFMPEG_EXE")
    if env:
        found = shutil.which(env) or (env if Path(env).is_file() else None)
        if found:
            return FfmpegLocation(found, "env")
    on_path = shutil.which("ffmpeg")
    if on_path:
        return FfmpegLocation(on_path, "PATH")
    try:
        import imageio_ffmpeg
        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled and Path(bundled).is_file():
            return FfmpegLocation(bundled, "bundled")
    except Exception:
        pass
    return FfmpegLocation(None, "none")


def ffmpeg_exe() -> str:
    """Path to ffmpeg, or the bare name so a later run fails with a clear error."""
    return resolve_ffmpeg().path or "ffmpeg"


_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")


def _secs(m) -> float:
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def probe_duration(ffmpeg: str, path) -> float:
    """Audio length in seconds using only ffmpeg.

    Reads the container "Duration:" line from `ffmpeg -i`; if the container has
    none (e.g. raw streams), decodes to null and takes the last reported time.
    Raises RuntimeError with the ffmpeg output tail if neither works.
    """
    path = str(path)
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise RuntimeError(f"could not run ffmpeg ({ffmpeg}): {e}") from e
    m = _DURATION_RE.search(r.stderr)
    if m:
        return _secs(m)
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path, "-vn", "-f", "null", "-"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise RuntimeError(f"could not run ffmpeg ({ffmpeg}): {e}") from e
    times = _TIME_RE.findall(r.stderr.replace("\r", "\n"))
    if r.returncode == 0 and times:
        h, mi, s = times[-1]
        return int(h) * 3600 + int(mi) * 60 + float(s)
    raise RuntimeError(f"could not read duration of {path}: {r.stderr[-400:]}")
