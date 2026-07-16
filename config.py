"""App configuration stored in config.json next to the app."""

import json
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULTS = {
    "engine": "local",          # "local" (Whisper on this PC) or "gemini" (Google API)
    "gemini_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "device": "auto",           # "auto" = NVIDIA GPU if available else CPU; "cpu" = force CPU
    "whisper_model": "large-v3",  # large-v3 | medium | small | base
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def save(cfg: dict):
    full = load()
    full.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    CONFIG_PATH.write_text(json.dumps(full, indent=1), encoding="utf-8")
