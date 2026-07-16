"""Meeting summary generation.

Prefers a local Ollama LLM if one is running (best quality, understands
Malay + English). Falls back to a built-in extractive summarizer otherwise.
"""

import re
from collections import Counter

import requests

OLLAMA_URL = "http://localhost:11434"
# tried in order; first one that exists locally is used
PREFERRED_MODELS = ["qwen2.5:7b", "qwen2.5:3b", "llama3.2", "llama3.1", "gemma2", "mistral"]

# common function words in both languages, so extractive scoring
# focuses on content words
STOPWORDS = set("""
yang dan di ke dari untuk dengan pada ini itu ada tidak tak akan kita kami
saya awak anda dia mereka ia adalah ialah dalam atas bagi juga sudah telah
boleh nak hendak macam sebab kerana jadi kalau bila apa siapa mana bagaimana
kenapa berapa lah kan pun sahaja saja lagi masih baru semua setiap para oleh
the a an and or but if then of to in on at for with from by is are was were
be been being have has had do does did will would can could shall should may
might must not no yes so as it its this that these those i you he she we they
them his her our your my me us am what which who whom when where why how all
""".split())


def ollama_model() -> str | None:
    """Return the name of a usable local Ollama model, or None."""
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return None
    if not names:
        return None
    for pref in PREFERRED_MODELS:
        for n in names:
            if n.startswith(pref):
                return n
    return names[0]


def _ollama_summarize(text: str, model: str) -> str:
    prompt = (
        "You are summarizing a meeting transcript. The meeting may be in Malay, "
        "English, or a mix of both. Write the summary in the SAME dominant "
        "language as the transcript.\n\n"
        "Produce markdown with these sections:\n"
        "## Ringkasan / Overview\n"
        "## Perkara Utama / Key Points (bullets)\n"
        "## Keputusan / Decisions (bullets, or '-' if none)\n"
        "## Tindakan / Action Items (bullets with owner if mentioned)\n\n"
        f"Transcript:\n{text[:24000]}"
    )
    r = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False,
              "options": {"temperature": 0.3, "num_ctx": 8192}},
        timeout=600,
    )
    r.raise_for_status()
    return r.json()["generated"] if "generated" in r.json() else r.json()["response"]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 20]


def _extractive(segments: list[dict], speaker_names: dict) -> str:
    """Frequency-based extractive summary; language-agnostic."""
    full = " ".join(s["text"] for s in segments)
    sents = _sentences(full)
    if not sents:
        return "_Transkrip terlalu pendek untuk diringkaskan. / Transcript too short to summarize._"

    words = re.findall(r"[a-zA-ZÀ-ɏ']+", full.lower())
    freq = Counter(w for w in words if w not in STOPWORDS and len(w) > 2)
    top_words = [w for w, _ in freq.most_common(12)]

    def score(s):
        ws = re.findall(r"[a-zA-ZÀ-ɏ']+", s.lower())
        if not ws:
            return 0
        return sum(freq.get(w, 0) for w in ws if w not in STOPWORDS) / (len(ws) ** 0.5)

    n_pick = max(5, min(12, len(sents) // 15))
    ranked = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)[:n_pick]
    picked = [sents[i] for i in sorted(ranked)]

    # speaker talk-time
    talk = Counter()
    for s in segments:
        talk[s["speaker"]] += s["end"] - s["start"]
    total = sum(talk.values()) or 1
    speaker_lines = []
    for spk, secs in talk.most_common():
        name = speaker_names.get(str(spk), f"Speaker {spk + 1}" if spk >= 0 else "Unknown")
        speaker_lines.append(f"- **{name}**: {secs / 60:.1f} min ({100 * secs / total:.0f}%)")

    return "\n".join([
        "## Perkara Utama / Key Points",
        *[f"- {s}" for s in picked],
        "",
        "## Topik Kerap Disebut / Frequent Topics",
        "- " + ", ".join(top_words),
        "",
        "## Pembahagian Percakapan / Speaking Time",
        *speaker_lines,
        "",
        "> _Ringkasan automatik (extractive). Untuk ringkasan AI yang lebih baik, "
        "pasang [Ollama](https://ollama.com) dan jalankan `ollama pull qwen2.5:7b`, "
        "kemudian tekan butang regenerate. / Automatic extractive summary — install "
        "Ollama for a proper AI-written summary, then hit regenerate._",
    ])


def summarize(segments: list[dict], speaker_names: dict) -> tuple[str, str]:
    """Returns (summary_markdown, engine_name)."""
    model = ollama_model()
    if model:
        lines = []
        for s in segments:
            name = speaker_names.get(str(s["speaker"]),
                                     f"Speaker {s['speaker'] + 1}" if s["speaker"] >= 0 else "?")
            lines.append(f"{name}: {s['text']}")
        try:
            return _ollama_summarize("\n".join(lines), model), f"ollama:{model}"
        except Exception as e:
            print(f"[summarizer] ollama failed: {e}", flush=True)
    return _extractive(segments, speaker_names), "extractive"
