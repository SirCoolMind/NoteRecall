"""How long a transcript line can really have lasted.

Whisper sometimes stretches a line's end time across a long silence: a line of
a few words that "lasts" several minutes. Nobody speaks that slowly, and the
stretch paints the speaker ribbon wrongly, inflates that speaker's talk time
by minutes, and can hand the line to whoever spoke most during the silence.

The rule is deliberately generous, so only impossible lengths are touched:
a line may last 10 seconds plus half a second per character. Ordinary speech
is around 12 to 15 characters per second; this allows 2. The start time is
never changed, because that is where playback jumps to.

static/js/ribbon.js has the same rule (spokenEnd) for the browser.
"""

BASE_SECONDS = 10.0
SECONDS_PER_CHAR = 0.5


def longest_plausible(text: str) -> float:
    return BASE_SECONDS + SECONDS_PER_CHAR * len(text or "")


def spoken_end(seg: dict) -> float:
    """The line's end time, cut back when its length is impossible for its text."""
    start = float(seg.get("start") or 0)
    end = float(seg.get("end") or 0)
    if not seg.get("text"):
        return end   # no text to judge by
    return min(end, round(start + longest_plausible(seg.get("text", "")), 2))


def spoken_seconds(seg: dict) -> float:
    return max(0.0, spoken_end(seg) - float(seg.get("start") or 0))
