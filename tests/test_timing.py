"""Impossible line lengths: Whisper can stretch a short line across a long silence. The rule in
timing.py cuts such a line's end back; ordinary lines are never touched."""

import numpy as np

import pipeline
import summarizer
import timing
from test_corrections import seed


def seg(start, end, text, speaker=0):
    return {"start": start, "end": end, "text": text, "speaker": speaker}


def test_ordinary_lines_are_left_alone():
    assert timing.spoken_end(seg(10, 12.4, "Okay.")) == 12.4
    assert timing.spoken_end(seg(10, 22, "Okay.")) == 22          # a slow line with a pause is still fine
    long_text = "x" * 400
    assert timing.spoken_end(seg(0, 29.5, long_text)) == 29.5


def test_a_few_words_cannot_last_minutes():
    assert timing.spoken_end(seg(100, 1084, "Okay.")) == 112.5   # 10 s + 0.5 s x 5 characters
    assert timing.spoken_end(seg(0, 50, "x" * 29)) == 24.5
    assert timing.spoken_seconds(seg(100, 1084, "Okay.")) == 12.5
    assert timing.spoken_seconds(seg(5, 3, "Backwards")) == 0
    assert timing.spoken_end({"start": 0, "end": 500}) == 500   # no text: nothing to judge by


def test_the_browser_uses_the_same_rule():
    import re
    from pathlib import Path
    js = (Path(__file__).parent.parent / "static" / "js" / "ribbon.js").read_text(encoding="utf-8")
    base, per_char = re.search(r"start \+ (\d+) \+ ([\d.]+) \* seg\.text\.length", js).groups()
    assert (float(base), float(per_char)) == (timing.BASE_SECONDS, timing.SECONDS_PER_CHAR)


def test_new_transcripts_are_written_with_plausible_ends(monkeypatch):
    class Seg:
        def __init__(self, start, end, text):
            self.start, self.end, self.text = start, end, text

    class Info:
        duration, language = 1200.0, "ms"

    class Model:
        def transcribe(self, audio, **kw):
            return iter([Seg(0, 2, "Selamat pagi."), Seg(2, 986, "Okay."), Seg(990, 993, "Terima kasih.")]), Info()

    monkeypatch.setattr(pipeline, "get_whisper", lambda: (Model(), "cpu"))
    out, _, _ = pipeline.transcribe(np.zeros(16000, dtype=np.float32), None)
    assert [(s["start"], s["end"]) for s in out] == [(0, 2), (2, 14.5), (990, 993)]


def test_talk_time_in_the_built_in_summary_ignores_the_stretch():
    segments = [seg(0, 10, "Kita mula mesyuarat sekarang ya semua.", 0),
                seg(10, 900, "Okay.", 1),
                seg(900, 910, "Baik, terima kasih semua kerana hadir.", 0)]
    text = summarizer.extractive(segments, {})
    assert "**Speaker 1**: 0.3 min" in text     # 20 s
    assert "**Speaker 2**: 0.2 min" in text     # 12.5 s, not 14.8 minutes


def test_srt_export_ends_the_subtitle_when_the_line_ends(client, data_dir):
    mid = seed(data_dir, segments=[seg(0, 2, "Selamat pagi."), seg(2, 986, "Okay.", 1)])
    srt = client.get(f"/api/meetings/{mid}/export", params={"format": "srt"}).text
    assert "00:00:02,000 --> 00:00:14,500" in srt
    # the file on disk is not rewritten: existing meetings keep what the pipeline wrote
    import json
    assert json.loads((data_dir / mid / "transcript.json").read_text(encoding="utf-8"))[1]["end"] == 986
