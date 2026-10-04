"""The app version, read from the VERSION file at the repo root."""

from pathlib import Path


def read_version(base_dir: Path = Path(__file__).parent) -> str:
    try:
        text = (Path(base_dir) / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"
    return text or "0.0.0"


__version__ = read_version()
