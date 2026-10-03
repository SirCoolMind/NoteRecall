"""Cloud transcription engine: Google Gemini audio understanding.

Used when config engine = "gemini".

Why this does not use Gemini's timestamps
-----------------------------------------
Measured against local-Whisper ground truth on a real 15 minute meeting,
Gemini's timestamps are not trustworthy and fail differently every request:
  * one chunk returned a clean but fast-running clock (~1.66x, so the last
    line of a 14:49 recording claimed 24:07),
  * another returned "start": 0.002, 0.086, ... - every value ~zero,
  * another emitted "start": 1:05.6, which is not even valid JSON.

What IS reliable is the transcript text and the order it is emitted in. So we
ask Gemini for text only, and derive timing locally: voice-activity detection
gives the exact speech regions, and the text is laid across those regions in
proportion to its length. Scored against ground truth this gives a median
error of ~2s (max ~4s), versus ~400s for Gemini's own numbers.

Speakers: Gemini labels speakers per request, so labels from different chunks
are not the same people. Local diarization relabels the whole file when its
models are present; otherwise Gemini's per-chunk labels are used.
"""

import json
import re
import subprocess
import time
from pathlib import Path

import requests

import ffmpeg_tools

API_BASE = "https://generativelanguage.googleapis.com"

CHUNK_TARGET = 300.0     # aim for ~5 minute chunks
CHUNK_TOLERANCE = 90.0   # accept a silence gap within +/- this of the target
MIN_CHUNK = 60.0

PROMPT = """Transcribe this audio excerpt completely and verbatim.
It is part of a meeting, mostly in Malay and/or English (they may be mixed
within a sentence). Keep the original language exactly as spoken - do NOT
translate anything.

Label each speaker by voice as "S1", "S2", "S3"... in the order they first
speak in THIS excerpt.

Return ONLY a JSON array, in chronological order. Each element:
{"speaker": "S1", "text": "..."}

Rules:
- Do NOT include timestamps or times of any kind.
- Split the transcript at natural sentence boundaries.
- Transcribe the excerpt from its beginning to its end, leaving nothing out.
%(hint)s"""


# ---------------------------------------------------------------- ffmpeg

def _to_mp3(ffmpeg_exe: str, src: Path, dst: Path, start: float = None, length: float = None):
    """Mono 16 kHz 48 kbps mp3 - small upload, plenty for speech."""
    cmd = [ffmpeg_exe, "-y"]
    if start is not None:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if length is not None:
        cmd += ["-t", f"{length:.3f}"]
    cmd += ["-ac", "1", "-ar", "16000", "-b:a", "48k", "-vn", str(dst)]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {r.stderr[-400:]}")


# ---------------------------------------------------------------- timeline

def _speech_regions(wav_path: Path, duration: float) -> list[tuple[float, float]]:
    """Where is there actually speech? Silero VAD (tiny, CPU, bundled with
    faster-whisper). Without it we treat the file as continuous speech, which
    only costs accuracy in recordings with long silent stretches."""
    try:
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        import pipeline as pl
        audio = pl.load_wav(wav_path)
        vad = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=400,
                                                      threshold=0.35))
        regions = [(v["start"] / 16000, v["end"] / 16000) for v in vad]
        if regions:
            return regions
    except Exception as e:
        print(f"[gemini] Silero VAD unavailable ({e}); treating file as continuous speech",
              flush=True)
    return [(0.0, duration)]


def _plan_chunks(duration: float, speech: list[tuple[float, float]]) -> list[dict]:
    """Split the timeline at gaps between speech, near CHUNK_TARGET, so no
    sentence is cut in half."""
    gaps = [((speech[i][1] + speech[i + 1][0]) / 2) for i in range(len(speech) - 1)]
    chunks, pos = [], 0.0
    while duration - pos > CHUNK_TARGET + CHUNK_TOLERANCE:
        target = pos + CHUNK_TARGET
        cands = [g for g in gaps if pos + MIN_CHUNK < g < duration - MIN_CHUNK / 2
                 and abs(g - target) <= CHUNK_TOLERANCE]
        cut = min(cands, key=lambda g: abs(g - target)) if cands else target
        chunks.append({"start": pos, "end": cut})
        pos = cut
    chunks.append({"start": pos, "end": duration})
    return chunks


def _split_sentences(text: str) -> list[str]:
    """Finer segments => a more precise 'currently speaking' highlight."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    return parts or [text]


def _layout(items: list[tuple[str, str]],
            regions: list[tuple[float, float]]) -> list[dict]:
    """Place ordered text across the speech regions, weighted by text length.

    Silence is skipped, so gaps in the conversation don't smear the timing."""
    pieces = []
    for spk, text in items:
        for sent in _split_sentences(text):
            pieces.append((spk, sent))
    if not pieces or not regions:
        return []
    total_w = sum(max(len(t), 1) for _, t in pieces)
    total_s = sum(e - s for s, e in regions)

    def at(speech_offset: float) -> float:
        left = speech_offset
        for s, e in regions:
            d = e - s
            if left <= d:
                return s + left
            left -= d
        return regions[-1][1]

    out, acc = [], 0.0
    for spk, text in pieces:
        out.append({"start": round(at(acc * total_s / total_w), 2),
                    "speaker_raw": spk, "text": text})
        acc += max(len(text), 1)
    return out


# ---------------------------------------------------------------- gemini api

def _upload_file(api_key: str, path: Path) -> str:
    size = path.stat().st_size
    r = requests.post(
        f"{API_BASE}/upload/v1beta/files",
        headers={"x-goog-api-key": api_key,
                 "X-Goog-Upload-Protocol": "resumable",
                 "X-Goog-Upload-Command": "start",
                 "X-Goog-Upload-Header-Content-Length": str(size),
                 "X-Goog-Upload-Header-Content-Type": "audio/mp3",
                 "Content-Type": "application/json"},
        json={"file": {"display_name": path.name}}, timeout=60)
    r.raise_for_status()
    upload_url = r.headers["x-goog-upload-url"]

    with open(path, "rb") as f:
        r = requests.post(upload_url, headers={
            "Content-Length": str(size), "X-Goog-Upload-Offset": "0",
            "X-Goog-Upload-Command": "upload, finalize"}, data=f, timeout=1800)
    r.raise_for_status()
    info = r.json()["file"]

    for _ in range(120):
        if info.get("state") == "ACTIVE":
            return info["uri"]
        if info.get("state") == "FAILED":
            raise RuntimeError("Gemini file processing failed")
        time.sleep(3)
        g = requests.get(f"{API_BASE}/v1beta/{info['name']}",
                         headers={"x-goog-api-key": api_key}, timeout=30)
        g.raise_for_status()
        info = g.json()
    raise RuntimeError("Gemini file processing timed out")


def _generate(api_key: str, model: str, file_uri: str, prompt: str) -> str:
    body = {"contents": [{"parts": [
                {"file_data": {"mime_type": "audio/mp3", "file_uri": file_uri}},
                {"text": prompt}]}],
            "generationConfig": {"temperature": 0.1,
                                 "responseMimeType": "application/json"}}
    # Google returns 503 "high demand" often enough that a thin retry loses a
    # whole meeting's work partway through; back off patiently instead.
    backoff = [5, 15, 30, 60, 90, 120]
    last = None
    for attempt in range(len(backoff) + 1):
        r = requests.post(f"{API_BASE}/v1beta/models/{model}:generateContent",
                          headers={"x-goog-api-key": api_key,
                                   "Content-Type": "application/json"},
                          json=body, timeout=1800)
        if r.status_code == 200:
            out = r.json()
            try:
                return out["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError):
                raise RuntimeError(f"Unexpected Gemini response: {json.dumps(out)[:300]}")
        last = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code in (429, 500, 502, 503) and attempt < len(backoff):
            wait = backoff[attempt]
            print(f"[gemini] {r.status_code} from Google, retrying in {wait}s "
                  f"({attempt+1}/{len(backoff)})", flush=True)
            time.sleep(wait)
            continue
        break
    raise RuntimeError(f"Gemini API error - {last}")


def _extract(text: str) -> list[tuple[str, str]]:
    """(speaker, text) in emission order, tolerating malformed JSON -
    Gemini has been observed returning arrays that don't parse."""
    txt = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        data = json.loads(txt)
        if isinstance(data, list):
            out = [(str(o.get("speaker", "S1")), str(o.get("text", "")).strip())
                   for o in data if isinstance(o, dict) and str(o.get("text", "")).strip()]
            if out:
                return out
    except json.JSONDecodeError:
        pass
    out = []
    for m in re.finditer(r"\{[^{}]*\}", txt):  # salvage object by object
        blk = m.group(0)
        t = re.search(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"', blk)
        if not t:
            continue
        s = re.search(r'"speaker"\s*:\s*"([^"]*)"', blk)
        try:
            val = json.loads('"' + t.group(1) + '"')
        except json.JSONDecodeError:
            val = t.group(1)
        if val.strip():
            out.append((s.group(1) if s else "S1", val.strip()))
    return out


# ---------------------------------------------------------------- pipeline

def transcribe_gemini(audio_path: Path, work_dir: Path, language: str | None,
                      cfg: dict, ffmpeg_exe: str, status_cb):
    api_key = (cfg.get("gemini_api_key") or "").strip()
    if not api_key:
        raise RuntimeError("Gemini engine selected but no API key set (see Setup page)")
    model = cfg.get("gemini_model") or "gemini-2.5-flash"

    status_cb("converting", 2)
    full_mp3 = work_dir / "_full.mp3"
    _to_mp3(ffmpeg_exe, audio_path, full_mp3)
    duration = ffmpeg_tools.probe_duration(ffmpeg_exe, full_mp3)
    if duration <= 0:
        raise RuntimeError("could not read audio duration")

    # local timeline: where speech actually is (Gemini is never asked for time)
    wav = work_dir / "_vad.wav"
    import pipeline as pl
    pl.convert_to_wav(audio_path, wav)
    speech = _speech_regions(wav, duration)
    chunks = _plan_chunks(duration, speech)
    print(f"[gemini] {duration:.0f}s audio, {len(speech)} speech regions "
          f"-> {len(chunks)} chunk(s)", flush=True)

    hint = {"ms": "- The audio is in Malay.",
            "en": "- The audio is in English."}.get(language or "", "")
    all_segs = []
    for i, ch in enumerate(chunks):
        status_cb("transcribing", 8 + 80 * i / len(chunks))
        clen = ch["end"] - ch["start"]
        part = work_dir / f"_chunk{i}.mp3"
        _to_mp3(ffmpeg_exe, full_mp3, part, start=ch["start"], length=clen)
        try:
            uri = _upload_file(api_key, part)
            items = _extract(_generate(api_key, model, uri, PROMPT % {"hint": hint}))
        finally:
            part.unlink(missing_ok=True)
        regions = [(max(s, ch["start"]), min(e, ch["end"])) for s, e in speech
                   if e > ch["start"] and s < ch["end"]] or [(ch["start"], ch["end"])]
        segs = _layout(items, regions)
        for s in segs:
            s["speaker_raw"] = f"c{i}:{s['speaker_raw']}"
        all_segs.extend(segs)
        print(f"[gemini] chunk {i+1}/{len(chunks)} [{ch['start']:.0f}-{ch['end']:.0f}s]"
              f" -> {len(items)} items, {len(segs)} segments", flush=True)

    full_mp3.unlink(missing_ok=True)
    if not all_segs:
        raise RuntimeError("Gemini returned no transcript")

    for i, s in enumerate(all_segs):  # end = next start, capped
        nxt = all_segs[i + 1]["start"] if i + 1 < len(all_segs) else duration
        s["end"] = round(max(s["start"] + 0.4, min(nxt, s["start"] + 30, duration)), 2)

    # Gemini's speaker labels only mean something within one chunk, so prefer
    # local diarization for labels consistent across the whole recording.
    status_cb("diarizing", 88)
    speakers_by = "gemini (per chunk)"
    try:
        if pl.SEG_MODEL.exists() and pl.EMB_MODEL.exists():
            turns = pl.diarize(pl.load_wav(wav), cfg.get("num_speakers") or None,
                               lambda f: status_cb("diarizing", 88 + f * 6))
            if turns:
                for s in all_segs:
                    s["speaker"] = -1
                pl.assign_speakers(all_segs, turns)
                speakers_by = "local diarization"
    except Exception as e:
        print(f"[gemini] local diarization unavailable ({e}); using Gemini labels", flush=True)
    wav.unlink(missing_ok=True)

    if speakers_by != "local diarization":
        ids: dict[str, int] = {}
        for s in all_segs:
            ids.setdefault(s["speaker_raw"], len(ids))
            s["speaker"] = ids[s["speaker_raw"]]

    for s in all_segs:
        s.pop("speaker_raw", None)

    status_cb("summarizing", 95)
    return {"segments": all_segs, "language": language or "ms",
            "duration": round(duration, 1),
            "num_speakers": len({s["speaker"] for s in all_segs}),
            "speakers_by": speakers_by, "chunks": len(chunks)}


def test_key(api_key: str, model: str) -> dict:
    try:
        r = requests.get(f"{API_BASE}/v1beta/models/{model}",
                         headers={"x-goog-api-key": api_key.strip()}, timeout=15)
        if r.status_code == 200:
            return {"ok": True, "message": f"Key valid, model '{model}' available"}
        msg = r.json().get("error", {}).get("message", r.text[:200])
        return {"ok": False, "message": f"HTTP {r.status_code}: {msg}"}
    except Exception as e:
        return {"ok": False, "message": str(e)}
