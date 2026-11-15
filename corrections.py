"""Corrections to a finished transcript: fix a line's text, give a line or a
whole turn to another speaker, delete a line, merge two speakers.

Everything here works on the plain list of segments from transcript.json and
changes it in place. Nothing touches the disk except backup_once / discard,
which keep the untouched transcript beside the corrected one so the user can
always go back:

    data/<id>/transcript.json            what the app shows (with corrections)
    data/<id>/transcript.original.json   as the pipeline wrote it; exists only
                                         once something has been corrected

A corrected line keeps its own original text in an "orig" field, so one line
can be put back without discarding everything else.
"""

import json
from pathlib import Path

ORIGINAL_FILE = "transcript.original.json"
MAX_TEXT = 2000   # one line of speech; a guard, not a feature


class CorrectionError(ValueError):
    """The request cannot be applied (bad index, stale line, bad speaker)."""


def has_backup(d: Path) -> bool:
    return (d / ORIGINAL_FILE).exists()


def backup_once(d: Path, segments: list, speaker_names: dict):
    """Keep the pipeline's transcript before the first correction. Later
    corrections leave the backup alone, so it stays the true original."""
    p = d / ORIGINAL_FILE
    if p.exists():
        return
    p.write_text(json.dumps({"segments": segments, "speaker_names": dict(speaker_names or {})},
                            ensure_ascii=False), encoding="utf-8")


def read_backup(d: Path) -> dict:
    data = json.loads((d / ORIGINAL_FILE).read_text(encoding="utf-8"))
    if not isinstance(data.get("segments"), list):
        raise CorrectionError("the saved original is not readable")
    return {"segments": data["segments"], "speaker_names": data.get("speaker_names") or {}}


def drop_backup(d: Path):
    (d / ORIGINAL_FILE).unlink(missing_ok=True)


def locate(segments: list, index: int, start) -> dict:
    """The segment at `index`, checked against the start time the browser saw,
    so an edit can never land on a different line after a re-transcribe."""
    if not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(segments):
        raise CorrectionError("that line does not exist any more")
    seg = segments[index]
    if start is not None:
        try:
            same = abs(float(start) - float(seg.get("start", 0))) < 0.011
        except (TypeError, ValueError):
            same = False
        if not same:
            raise CorrectionError("the transcript changed; reload the meeting")
    return seg


def clean_text(text) -> str:
    if not isinstance(text, str):
        raise CorrectionError("text must be a string")
    text = " ".join(text.split())
    if not text:
        raise CorrectionError("a line cannot be empty; delete it instead")
    if len(text) > MAX_TEXT:
        raise CorrectionError("that is too long for one line")
    return text


def set_text(seg: dict, text: str) -> bool:
    """Replace a line's text, remembering the original. Typing the original
    back clears the mark. Returns True when something changed."""
    text = clean_text(text)
    if text == seg.get("text"):
        return False
    original = seg.get("orig", seg.get("text", ""))
    seg["text"] = text
    if text == original:
        seg.pop("orig", None)
    else:
        seg["orig"] = original
    return True


def restore_text(seg: dict) -> bool:
    if "orig" not in seg:
        return False
    seg["text"] = seg.pop("orig")
    return True


def turn_range(segments: list, index: int) -> range:
    """Indexes of the turn that line `index` belongs to: the run of
    neighbouring lines with the same speaker."""
    spk = segments[index].get("speaker", -1)
    lo = index
    while lo > 0 and segments[lo - 1].get("speaker", -1) == spk:
        lo -= 1
    hi = index
    while hi + 1 < len(segments) and segments[hi + 1].get("speaker", -1) == spk:
        hi += 1
    return range(lo, hi + 1)


def speakers_in(segments: list) -> list[int]:
    return sorted({s.get("speaker", -1) for s in segments if s.get("speaker", -1) >= 0})


def new_speaker_id(segments: list) -> int:
    found = speakers_in(segments)
    return (found[-1] + 1) if found else 0


def set_speaker(segments: list, index: int, speaker, whole_turn: bool = False) -> list[int]:
    """Give line `index` (or its whole turn) to `speaker`: an existing speaker
    number, or "new" for a speaker nobody has yet. Returns the changed indexes."""
    if speaker == "new":
        speaker = new_speaker_id(segments)
    elif not isinstance(speaker, int) or isinstance(speaker, bool) or speaker not in speakers_in(segments):
        raise CorrectionError("unknown speaker")
    targets = turn_range(segments, index) if whole_turn else [index]
    changed = [i for i in targets if segments[i].get("speaker", -1) != speaker]
    for i in changed:
        segments[i]["speaker"] = speaker
    return changed


def merge_speakers(segments: list, speaker_names: dict, source: int, into: int) -> list[int]:
    """Everything `source` said becomes `into`'s. A custom name moves across
    when `into` has none. Returns the changed indexes."""
    found = speakers_in(segments)
    for spk in (source, into):
        if not isinstance(spk, int) or isinstance(spk, bool) or spk not in found:
            raise CorrectionError("unknown speaker")
    if source == into:
        raise CorrectionError("pick two different speakers")
    changed = [i for i, s in enumerate(segments) if s.get("speaker", -1) == source]
    for i in changed:
        segments[i]["speaker"] = into
    name = speaker_names.pop(str(source), None)
    if name and not speaker_names.get(str(into)):
        speaker_names[str(into)] = name
    return changed


def is_corrected(segments: list) -> bool:
    return any("orig" in s for s in segments)
