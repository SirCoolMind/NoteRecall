# NoteRecall

Turns long meeting recordings into accurate, speaker-labelled transcripts with
summaries. Built for meetings in **Bahasa Melayu, English, or a mix of both**
(bahasa rojak / code-switching mid-sentence).

Local-first: by default everything runs on your own machine and **no audio
leaves it**. A Google Gemini cloud engine is available as an opt-in alternative.

| | |
|---|---|
| **Docs** | [Project summary](docs/summary.md) · [Deploy on Linux + nginx](docs/deploy-nginx.md) · [Testing under WSL](docs/testing-linux.md) |
| **Pages** | `/` the app · `/setup` requirements & settings · `/about` how it works |

---

## Run it locally

**One step.** Windows: double-click `start.bat`. macOS / Linux: run `./start.sh`.
No Python needs to be installed first. The launcher:

1. installs [uv](https://docs.astral.sh/uv/) if it is missing;
2. creates `.venv` with Python 3.12 (uv downloads Python itself);
3. installs `requirements.txt` (includes a bundled ffmpeg via `imageio-ffmpeg`),
   plus `requirements-gpu.txt` (~2.3 GB of CUDA libraries) **only** if
   `nvidia-smi` finds an NVIDIA card;
4. downloads the speaker models (~165 MB) into `models/` once (the whisper
   model is fetched on first use, or from the in-app setup);
5. starts the server on <http://127.0.0.1:8756> and opens your browser as soon
   as the server responds.

Running the launcher again on a ready machine skips straight to starting the
server (a stamp in `.venv/` records the installed requirements).

**Manual fallback**

```bash
# install uv: https://docs.astral.sh/uv/getting-started/installation/
uv venv --python 3.12
uv pip install -r requirements.txt
uv pip install -r requirements-gpu.txt     # NVIDIA GPU only
# activate the venv, or call .venv/bin/python (Windows: .venv\Scripts\python.exe)
python server.py
```

Then open <http://127.0.0.1:8756>.

### Requirements

`/setup` checks everything and gives **click-to-expand install steps for
Windows and Linux**, plus an **"Ask an AI to install this for me"** button that
generates a prompt describing exactly what your machine is missing.

- Any engine: `requirements.txt` (CPU-ready). Python and ffmpeg come with it.
- NVIDIA GPU only: also `requirements-gpu.txt` (~2.3 GB of CUDA
  libraries — skip it on CPU-only machines).

**You do not need a GPU.** `large-v3` on 8 CPU threads does ~24 min per hour of
audio with identical accuracy. Tested on Ubuntu 24.04.

---

## Host it on a Linux server (nginx)

Full recipe — systemd unit, nginx config, TLS, troubleshooting:
**[docs/deploy-nginx.md](docs/deploy-nginx.md)** (verified on Ubuntu 24.04 /
nginx 1.24).

> ### ⚠️ Read before exposing it
>
> **The app has no login.** Anyone who can reach the port can read every
> transcript, download the audio, replace your Gemini API key, and delete
> meetings. Bind it to `127.0.0.1` and let nginx handle auth. Never run
> `HOST=0.0.0.0` on a network you don't control.

The three settings that actually matter:

```nginx
server {
    listen 80;
    server_name meetings.example.com;

    # nginx defaults to 1 MB, which fails EVERY upload with 413.
    client_max_body_size 2g;

    # The only thing protecting the app.
    auth_basic           "NoteRecall";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass http://127.0.0.1:8756;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_request_buffering off;   # stream uploads, don't spool to disk
        proxy_buffering off;           # audio seeking uses HTTP Range (206)
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }
}
```

Run the app itself as a systemd service on `127.0.0.1:8756`:

```ini
[Service]
User=meetings
WorkingDirectory=/opt/meeting-transcriber
Environment=HOST=127.0.0.1
Environment=PORT=8756
Environment=HF_HOME=/opt/meeting-transcriber/.cache/huggingface
ExecStart=/opt/meeting-transcriber/.venv/bin/python server.py
Restart=on-failure
```

---

## What it does

- **Upload** a recording (mp3 / wav / m4a / mp4 / ogg) — 1–2 hour meetings are fine
- **Transcribe** with Whisper `large-v3`, on GPU or CPU
- **Identify speakers** — click any name in the transcript to rename them
  ("Speaker 1" → "Puan Aisyah"); it applies everywhere, including exports
- **Set the speaker count if you know it.** Auto-detect over-splits on echoey
  meeting rooms. Use the upload form, or **↻ Re-detect speakers** afterwards
  (fast — it redoes only the labels, keeping the transcript)
- **Language**: auto-detect, or force Bahasa Melayu / English per upload
- **Meeting list** with live status and progress
- **Floating player** that follows the transcript as it plays — click a line to
  jump there, or click the progress bar to move the transcript
- **Search** within a transcript
- **Summary tab**: key points, frequent topics, speaking-time split
- **Export** as `.txt`, `.md` (with summary), or `.srt`
- **↻ Re-transcribe** any meeting with the current engine, without re-uploading

## Choosing a model

**Use `large-v3`.** Smaller models don't just mishear bahasa rojak — they
silently *translate* your English into Malay, which reads fluently and is not
what was said. Measured on real meeting audio, CPU-only:

| model | speed | "I'm the leader for the infrastructure" became |
|---|---|---|
| `base` | 5.5× realtime | "I'm Charles from Y&E… doing a four on the infrastructure" |
| `medium` | 3.7× realtime | "saya akan menulis tentang impran" — translated |
| **`large-v3`** | **2.5× realtime** | correct ✓ |

`large-v3` is only ~2× slower than `base`, so `base`/`small` are no longer
offered. Details in [docs/summary.md §5](docs/summary.md).

## The cloud (Gemini) engine

Gemini's own timestamps are unusable and fail differently on every request —
measured against local-Whisper ground truth on a real 15-minute meeting: one
chunk's clock ran 1.66× fast (the last line of a 14:49 recording claimed
24:07), another returned every timestamp as ~0, another emitted
`"start": 1:05.6` — not valid JSON.

So the app never asks Gemini for time. It uses what Gemini is good at (the
words and their order) and reconstructs timing locally with Silero VAD.

| approach | median timestamp error |
|---|---|
| Gemini's own timestamps | ~401 s |
| chunked + re-anchored | ~12 s |
| **text-only + local VAD layout (current)** | **~1.8 s** (max 7.4 s) |

Speakers in cloud mode come from local diarization, because Gemini's "S1" in
one chunk isn't "S1" in the next. Cloud mode uploads your audio to Google
(kept ~48 h) — don't use it for confidential meetings.

## Better summaries (optional)

The built-in summary is extractive. For a proper AI-written summary in
Malay/English, install [Ollama](https://ollama.com) and:

```bash
ollama pull qwen2.5:7b
```

The app auto-detects it — hit **↻ Regenerate summary** on any meeting.

## Where data lives

- `data/<meeting-id>/` — audio, `transcript.json`, `summary.md`, `meta.json`.
  Deleting a meeting in the UI removes the folder permanently.
- `models/` — speaker models (~165 MB)
- Whisper cache (~3 GB) — `~/.cache/huggingface`, or wherever `HF_HOME` points
- `config.json` — settings **and your Gemini API key in plain text**. Don't commit it.

## Performance

| | 1-hour meeting |
|---|---|
| GPU (RTX 4050) | ~13 min |
| CPU only (8 threads) | ~24 min, same accuracy |

More CPU threads is *slower*, not faster — the cap of 8 is deliberate, see
[docs/summary.md](docs/summary.md).

## Files

| | |
|---|---|
| `server.py` | FastAPI app, job queue, meeting CRUD, setup checks, exports |
| `pipeline.py` | Local: ffmpeg → Whisper → diarize → merge |
| `engines.py` | Cloud: chunking, Gemini, VAD timing layout |
| `summarizer.py` | Ollama or extractive summaries |
| `config.py` | `config.json` load/save |
| `static/` | `index.html` (single-page app), `css/`, `js/`, `i18n/` (en, ms), vendored `fonts/`, `icons/`, `vendor/` |
| `requirements.txt` / `requirements-gpu.txt` | CPU deps / CUDA deps |
| `start.sh` / `start.bat` | Launchers |
| `docs/` | summary, nginx deployment, WSL testing |
