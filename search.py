"""Search everything said, in every finished meeting.

Plain files stay the only storage: this reads each data/<id>/transcript.json
and keeps the lowered text in memory, re-reading a file only when it changes
on disk. For a personal library (tens of meetings, a few thousand lines each)
a scan takes a few milliseconds, so there is no index to build or to go stale.

Matching is the same rule as the search box inside a meeting: the query as
typed, ignoring case, anywhere in a line. Results link to the line's start
time, so a hit opens the meeting at that moment.
"""

import json
from pathlib import Path

MIN_QUERY = 2          # one letter matches almost every line
HITS_PER_MEETING = 3   # shown on the schedule row; the rest are counted
SNIPPET = 180          # characters of a long line to show around the match

# meeting id -> (mtime_ns, size, [(start, speaker, text, lowered text)])
_cache: dict[str, tuple] = {}


def normalise(query: str) -> str:
    return " ".join(str(query or "").split()).casefold()


def _lines(d: Path) -> list[tuple]:
    p = d / "transcript.json"
    try:
        st = p.stat()
    except OSError:
        _cache.pop(d.name, None)
        return []
    hit = _cache.get(d.name)
    if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
        return hit[2]
    try:
        segments = json.loads(p.read_text(encoding="utf-8"))
        lines = [(float(s.get("start", 0)), int(s.get("speaker", -1)), str(s.get("text", "")),
                  str(s.get("text", "")).casefold()) for s in segments]
    except (OSError, ValueError, TypeError, AttributeError):
        return []   # mid-write or malformed: not searchable right now, never an error
    _cache[d.name] = (st.st_mtime_ns, st.st_size, lines)
    return lines


def snippet(text: str, at: int, length: int, limit: int = SNIPPET) -> str:
    """The whole line when it is short; otherwise a window around the match,
    cut at spaces, with an ellipsis on each cut side."""
    if len(text) <= limit:
        return text
    lo = max(0, at - (limit - length) // 2)
    hi = min(len(text), lo + limit)
    lo = max(0, hi - limit)
    if lo > 0:
        sp = text.find(" ", lo)
        lo = sp + 1 if 0 <= sp < at else lo
    if hi < len(text):
        sp = text.rfind(" ", lo, hi)
        hi = sp if sp > at + length else hi
    return ("…" if lo > 0 else "") + text[lo:hi].strip() + ("…" if hi < len(text) else "")


def find(data_dir: Path, query: str, per_meeting: int = HITS_PER_MEETING) -> dict:
    """{"query", "meetings": {id: {"total", "hits": [{"index", "start",
    "speaker", "text"}]}}, "total"}. Only finished meetings are searched.
    A query shorter than MIN_QUERY returns nothing."""
    needle = normalise(query)
    out = {"query": needle, "meetings": {}, "total": 0}
    if len(needle) < MIN_QUERY:
        return out
    seen = set()
    for d in data_dir.iterdir():
        try:
            meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("status") != "done":
            continue
        seen.add(d.name)
        total, hits = 0, []
        for index, (start, speaker, text, low) in enumerate(_lines(d)):
            at = low.find(needle)
            if at < 0:
                continue
            total += 1
            if len(hits) < per_meeting:
                # casefold can change a string's length (ß -> ss); then offsets
                # into the original are unreliable, so show the line from its start
                aligned = len(low) == len(text)
                hits.append({"index": index, "start": start, "speaker": speaker,
                             "text": snippet(text, at if aligned else 0, len(needle))})
        if total:
            out["meetings"][meta.get("id", d.name)] = {"total": total, "hits": hits}
            out["total"] += total
    for gone in set(_cache) - seen:   # deleted meetings leave the cache
        del _cache[gone]
    return out
