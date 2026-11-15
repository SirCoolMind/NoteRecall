"""Fetch the audio of a YouTube video, for the optional "YouTube links" setting.

Off by default (config "youtube_links"). yt-dlp is NOT in requirements.txt: it
is installed on request from Settings (installer step "yt_dlp"), so people who
never turn this on download nothing. Only the audio track comes in; nothing is
sent out except the request to YouTube itself.

Failures raise LinkError with a short code the screens translate.
"""

import importlib.util
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_SECONDS = 6 * 3600          # longer than any meeting; keeps a mistaken 24 h stream out
PLACEHOLDER_TITLE = "YouTube"   # shown until the video's own title is known

_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
          "youtu.be", "www.youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PATH_KINDS = ("shorts", "live", "embed", "v")


class LinkError(Exception):
    """code: bad_link | not_installed | unavailable | blocked | live | too_long | network | failed."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def video_url(text) -> str | None:
    """The canonical watch URL for one video, or None when `text` is not a YouTube
    video link. Playlist and tracking parameters are dropped on purpose: one link, one video."""
    if not isinstance(text, str):
        return None
    text = text.strip()
    if not text or len(text) > 500 or any(c.isspace() for c in text):
        return None
    if "://" not in text:
        text = "https://" + text
    try:
        u = urlparse(text)
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or host not in _HOSTS:
        return None
    parts = [p for p in u.path.split("/") if p]
    if host.endswith("youtu.be"):
        vid = parts[0] if parts else ""
    elif parts and parts[0] == "watch":
        vid = (parse_qs(u.query).get("v") or [""])[0]
    elif len(parts) >= 2 and parts[0] in _PATH_KINDS:
        vid = parts[1]
    else:
        vid = ""
    return f"https://www.youtube.com/watch?v={vid}" if _ID_RE.match(vid) else None


def available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def version() -> str:
    try:
        from yt_dlp.version import __version__
        return __version__
    except Exception:
        return ""


class _Quiet:
    """yt-dlp logger: keep its chatter out of the server console."""

    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


_UNAVAILABLE = ("private video", "unavailable", "sign in", "members-only", "members only",
                "age-restricted", "confirm your age", "has been removed", "not available",
                "account associated", "copyright")
_NETWORK = ("getaddrinfo", "timed out", "connection", "network is unreachable",
            "temporary failure in name resolution", "urlopen error", "ssl")


# YouTube refusing this connection, not this video: it answers every link the same way
# for a while ("Sign in to confirm you're not a bot", HTTP 429). Checked first, because
# the same text also says "sign in".
_BLOCKED = ("not a bot", "429", "too many requests")


def _code_for(message: str) -> str:
    low = message.lower()
    if any(s in low for s in _BLOCKED):
        return "blocked"
    if any(s in low for s in _UNAVAILABLE):
        return "unavailable"
    if any(s in low for s in _NETWORK):
        return "network"
    return "failed"


def fetch(url: str, dest_dir, progress=None) -> dict:
    """Download the audio track into dest_dir as audio.<ext>.
    progress(fraction 0..1) is called as bytes arrive.
    Returns {"file": name, "title": str, "duration": seconds or 0}."""
    if not available():
        raise LinkError("not_installed")
    import yt_dlp
    import ffmpeg_tools

    dest = Path(dest_dir)
    for old in dest.glob("audio.*"):     # a half-finished earlier try
        old.unlink(missing_ok=True)

    def hook(d):
        if progress and d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                progress(min(1.0, (d.get("downloaded_bytes") or 0) / total))

    opts = {
        # m4a first: every browser plays it, so the meeting page can too
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "outtmpl": str(dest / "audio.%(ext)s"),
        "noplaylist": True,
        "quiet": True, "no_warnings": True, "noprogress": True, "logger": _Quiet(),
        "progress_hooks": [hook],
        "ffmpeg_location": ffmpeg_tools.ffmpeg_exe(),
        "socket_timeout": 30,
        "retries": 3,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
                raise LinkError("live")
            duration = float(info.get("duration") or 0)
            if duration > MAX_SECONDS:
                raise LinkError("too_long")
            info = ydl.extract_info(url, download=True)
            path = Path((info.get("requested_downloads") or [{}])[0].get("filepath")
                        or ydl.prepare_filename(info))
    except LinkError:
        raise
    except Exception as e:   # yt_dlp.utils.DownloadError and anything it lets through
        message = str(e)
        raise LinkError(_code_for(message), message[-300:]) from e
    if not path.is_file():
        raise LinkError("failed", "no audio file was written")
    return {"file": path.name, "title": (info.get("title") or "").strip(), "duration": duration}
