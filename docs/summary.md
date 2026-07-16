# Meeting Transcriber — Project Summary

A local-first web app that turns long meeting recordings (1–2 hours) into
accurate, speaker-labelled transcripts with automatic summaries. Built for
meetings held in **Bahasa Melayu, English, or a mix of both** (bahasa rojak /
code-switching mid-sentence).

Runs entirely on your own laptop by default — audio never leaves the machine.
A cloud engine (Google Gemini) is available as an opt-in alternative.

---

## 1. What it does

| Capability | Detail |
|---|---|
| Transcribe | Whisper large-v3 on the local GPU, or Google Gemini via your own API key |
| Identify speakers | Diarization labels who spoke when; names are editable and stick everywhere |
| Languages | Auto-detect, or force Malay / English per upload. Handles mixed-language speech |
| Meeting library | List of all meetings with date, duration, speaker count, language, progress |
| Review | Floating player synced to the transcript — click a line to jump, click the progress bar to move the transcript |
| Summary | Key points, topics, and speaking-time split; better summaries via a local LLM (Ollama) if installed |
| Export | `.txt`, `.md` (with summary), `.srt` subtitles |
| Re-run | **Re-transcribe** a meeting with the currently selected engine (no re-upload), or **Re-detect speakers** to redo only the labels — useful when you know the real speaker count |
| Setup page | Requirements check with click-to-expand install steps for Windows **and** Linux, an "Ask an AI to install this for me" prompt generator, engine switch, device/model selection, architecture explainer |

## 2. Quick start

| | |
|---|---|
| **Linux/macOS** | `./start.sh` — creates the venv, installs `requirements.txt`, adds CUDA only if `nvidia-smi` finds a card, downloads the speaker models, starts the server |
| **Windows** | `start.bat` — **runs the app only**; it assumes `.venv` already exists. For a fresh Windows machine, follow the per-step instructions on `/setup` |

Then open <http://localhost:8756>:

| page | what |
|---|---|
| `/` | the app — upload, meeting list, transcript viewer |
| `/setup` | requirements check with per-OS install steps, engine + device settings |
| `/about` | what the project is, the pipeline, the tech stack |

Serve it on a LAN box with `HOST=0.0.0.0 PORT=8756 ./start.sh`.
For a real server behind nginx (systemd unit, upload limits, **authentication**),
see **[deploy-nginx.md](deploy-nginx.md)**.

### Linux notes

Local mode is **tested on Linux** (Ubuntu 24.04 / WSL2, Python 3.12): full
upload → Whisper → diarization → summary, CPU-only, both speakers correct.

- `pip install -r requirements.txt` — core + local engine, **no CUDA** (487 MB).
- `pip install -r requirements-gpu.txt` — **only** if `nvidia-smi` finds a card;
  it pulls ~2.3 GB of CUDA libraries that are useless on a CPU-only server.
  `start.sh` runs this automatically when it detects an NVIDIA GPU.
- Debian/Ubuntu: `python3 -m venv` fails with *"ensurepip is not available"*
  until `apt install -y python3-venv` — a separate package from `python3`.
- Two platform differences are handled in `pipeline._setup_cuda_dlls()`:
  `os.add_dll_directory` is Windows-only (calling it on Linux raised
  AttributeError before Whisper could load), and on Linux the CUDA `.so` files
  must be preloaded with `ctypes` — the dynamic loader reads `LD_LIBRARY_PATH`
  at process start, so setting it from Python is ignored.
- With `device: auto` and no GPU, it logs *"CUDA unavailable … falling back to
  CPU"* and continues **on the same model** — see the policy in §5.
- Under systemd, set `HF_HOME` so the service user has a writable model cache;
  the Setup check honours `HF_HOME` / `HF_HUB_CACHE`.
- See [testing-linux.md](testing-linux.md) for running it under WSL.

## 3. Architecture

### Local engine (default — private, free)

```
audio file
  → ffmpeg           convert to 16 kHz mono WAV
                     highpass (remove room rumble) + speechnorm (lift distant voices)
  → Whisper large-v3 speech → text with exact timestamps (GPU, via faster-whisper/CTranslate2)
                     Silero VAD skips silence
  → diarization      pyannote segmentation 3.0 (speech turns)
                     + NeMo TitaNet-Large (voice fingerprints)
                     + clustering (group turns by voice)   [sherpa-onnx, CPU]
  → merge            each sentence gets the speaker it overlaps most
  → summary          Ollama LLM if present, else built-in extractive
```

### Cloud engine (opt-in — needs your own Gemini API key)

```
audio file
  → ffmpeg           mono 48 kbps MP3, split into ~5 min chunks cut at silence
  → Gemini           TEXT ONLY — deliberately not asked for timestamps (see §4)
  → Silero VAD       find real speech regions locally
  → layout           lay Gemini's text across those regions, weighted by length
  → diarization      local, for speaker labels consistent across the whole file
  → summary          same as local
```

**Why speakers are detected locally even in cloud mode:** Gemini labels
speakers per request, so "S1" in one chunk is not the same person as "S1" in
the next. Local diarization relabels the whole recording consistently.

## 4. Key findings (measured, not assumed)

### Gemini's timestamps are unusable

Measured against local-Whisper ground truth on a real 15-minute meeting, the
same model failed three different ways across three chunks of one recording:

| chunk | what Gemini returned |
|---|---|
| 1 | clock running **1.66× too fast** — the last line of a 14:49 recording claimed **24:07** (linear, r=0.9996) |
| 2 | `"start": 0.002, 0.086, …` — every timestamp ≈ zero |
| 3 | `"start": 1:05.6` — not even valid JSON |

Its **text and ordering, however, are reliable**. So the app asks Gemini for
words only and reconstructs timing locally from voice-activity detection.

| approach | median timestamp error |
|---|---|
| Gemini's own timestamps | ~401 s |
| chunked + re-anchored to real time | ~12 s |
| **text-only + local VAD layout (shipped)** | **~1.8 s** (worst 7.4 s) |

Note: telling Gemini *"every start MUST be between 0 and 300"* made its
timestamps **worse**, not better — that instruction produced the all-zeros
output. It is not asked for time at all now.

### Speaker clustering must be tuned, and told the speaker count

The default clustering threshold over-split badly on real, echoey meeting-room
audio — a 52-minute meeting came back with **234 "speakers"**. A sweep across
thresholds on real audio (0.6 → 31 speakers, 0.8 → 20, 1.0 → 12, 1.2 → 2)
settled the shipped default at **1.0**.

Auto-detection still over-splits when the room echoes. **If you know how many
people spoke, set it** — it is dramatically more accurate than auto.

## 5. Performance (measured on this laptop)

Hardware: Intel i5-13500HX (14C/20T), 32 GB RAM, NVIDIA RTX 4050 Laptop (6 GB).

| job | audio | processing | speed |
|---|---|---|---|
| Local, Whisper large-v3 (GPU) + diarization | 52.6 min | 696 s | 4.5× realtime |
| Local, speaker re-detection only (CPU) | 52.6 min | 411 s | 7.7× realtime |
| Cloud, Gemini + local VAD + diarization | 14.8 min | 115 s | 7.7× realtime |
| Linux, Whisper large-v3 on **CPU** (transcribe only) | 1.6 min | 38 s | 2.5× realtime |

Rules of thumb for a 1-hour meeting:

- **GPU (RTX 4050): ~13 min.** First run after a reboot adds ~20 s to load the
  model into VRAM.
- **CPU only (8 threads): ~24 min**, same accuracy. Perfectly usable — you do
  not need a GPU for this app.

### Device vs model — don't confuse them

**The device sets the speed. The model sets the accuracy.** CPU is not "worse"
than GPU: it runs the identical weights and produces the same text, just
slower. Errors come from choosing a *small model*, not from using CPU.

Measured on 95 s of real Malay/English meeting audio, **all CPU-only** (20
cores, int8), transcribing *"By the way, I'm Syarul from IT. So, I'm the leader
for the infrastructure."*:

| model | speed | output |
|---|---|---|
| `base` | 17 s (5.5× realtime) | "I'm **Charles from Y&E**… **doing a four** on the infrastructure" |
| `small` | 24 s (3.9× realtime) | "Saya adalah **Charo** dari IT" — **translated to Malay** |
| `medium` | 25 s (3.7× realtime) | "saya **Syarod** dari IT… **menulis tentang impran**" — **translated** |
| **`large-v3`** | **38 s (2.5× realtime)** | **correct, code-switching preserved** ✓ |

Two conclusions:

1. **Small models don't just mishear bahasa rojak — they silently translate the
   English into Malay.** The output looks fluent and is simply not what was said.
   That is a worse failure than a garbled word, because it isn't obvious.
2. **`large-v3` costs almost nothing extra on CPU** — 2.5× realtime vs 5.5× for
   `base`, i.e. roughly **24 min for a 1-hour meeting with no GPU at all**.

**Project policy: `large-v3` always, on GPU or CPU.** This is an in-house tool —
correct text matters more than finishing sooner. Consequences in the code:

- `get_whisper()` deliberately does **not** downgrade the model when CUDA is
  missing. A quiet swap to `medium` would hand back wrong-language text.
- `base` and `small` are no longer offered in the Setup dropdown. An older
  config still set to one is shown as *"NOT recommended"* rather than silently
  accepted.

### CPU threads — do not raise the cap

Counter-intuitively, more threads is much slower. Measured, large-v3 int8, same
95 s clip, on a 20-thread CPU (6 P-cores + 8 E-cores):

| threads | time | speed |
|---|---|---|
| **8** | **38.5 s** | **2.5× realtime** |
| 16 | 134.1 s | 0.7× realtime |
| 20 | 187.7 s | 0.5× realtime |

`CPU_THREADS = min(8, os.cpu_count())` in `pipeline.py` is therefore both the
fastest setting and the one that keeps the machine usable during a job.

## 6. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Speech-to-text | **Whisper large-v3** via faster-whisper (CTranslate2) | Strongest open model for Malay + English and code-switching; 4–5× faster than reference Whisper |
| Speaker turns | **pyannote segmentation 3.0** | Standard, accurate speech-turn segmentation |
| Voice fingerprints | **NeMo TitaNet-Large** | Robust speaker embeddings |
| Diarization runtime | **sherpa-onnx** | CPU-only, no PyTorch, no HuggingFace token needed |
| Voice activity | **Silero VAD** (bundled with faster-whisper) | Tiny, CPU, accurate — used to skip silence and to time cloud transcripts |
| Audio | **ffmpeg** | Reads anything; filters for rumble + quiet voices |
| Cloud option | **Gemini 2.5 Flash** | Strong Malay; user-supplied key |
| Summaries | **Ollama** (qwen2.5) if present, else built-in extractive | Local LLM quality without a hard dependency |
| Backend | **FastAPI + uvicorn**, single background worker | Simple, one queue, survives restarts |
| Frontend | **Single-file vanilla HTML/CSS/JS** | No build step, no npm, opens instantly |
| Storage | **Plain files** on disk (`data/<id>/`) | Inspectable, portable, nothing to migrate |

## 7. Data, privacy & security

- Everything lives in `data/<meeting-id>/`: `audio.*`, `transcript.json`,
  `summary.md`, `meta.json`. Delete a meeting in the UI and the folder is gone.
- Models cache in `models/` (diarization, ~165 MB) and the HuggingFace cache
  (Whisper, ~3 GB) — `~/.cache/huggingface` unless `HF_HOME` says otherwise.
- Local engine: **nothing leaves the machine**, works offline.
- Cloud engine: **audio is uploaded to Google** and kept ~48 h on their side.
  The Setup page warns about this. Don't use it for confidential meetings.
- `config.json` holds the Gemini API key in plain text — don't commit it.
  `/api/config` returns it masked, but `POST /api/config` can overwrite it.

> ### ⚠️ The app has no authentication
>
> There is no login. **Anyone who can reach the port can read every transcript,
> download the audio, replace your Gemini API key, and delete meetings.** That
> is fine bound to `127.0.0.1` on your own laptop, and not fine anywhere else.
> Never expose it directly with `HOST=0.0.0.0` on an untrusted network — put it
> behind nginx with auth: see [deploy-nginx.md](deploy-nginx.md).

## 8. Files

| File | Role |
|---|---|
| `server.py` | FastAPI app, job queue, meeting CRUD, setup checks, exports |
| `pipeline.py` | Local pipeline: convert → Whisper → diarize → merge; model loading, device selection |
| `engines.py` | Cloud pipeline: chunking, Gemini calls, VAD timing layout, tolerant parsing |
| `summarizer.py` | Ollama or extractive summaries (Malay/English aware) |
| `config.py` | `config.json` load/save (engine, key, device, model) |
| `static/index.html` | The app UI (meeting list, transcript detail) |
| `static/setup.html` | `/setup` — requirements check, install steps, engine settings |
| `static/about.html` | `/about` — project & architecture explainer |
| `requirements.txt` | Core + local engine, CPU-ready (487 MB installed) |
| `requirements-gpu.txt` | CUDA libraries (~2.3 GB) — NVIDIA GPUs only |
| `start.bat`, `start.sh` | Launch scripts (Windows / Linux+macOS) |
| `config.json` | Local settings incl. the Gemini key — **not** for committing |
| `docs/summary.md` | This document |
| `docs/deploy-nginx.md` | Hosting on a Linux server: systemd, nginx, auth, TLS |
| `docs/testing-linux.md` | Running/testing under WSL |

### HTTP API (all unauthenticated — see §7)

| endpoint | purpose |
|---|---|
| `GET /`, `/setup`, `/about` | the three pages |
| `GET/POST /api/config`, `POST /api/config/test-gemini` | settings, key test |
| `GET /api/status`, `GET /api/setup` | badges; requirements + architecture |
| `POST /api/meetings` | upload (multipart: file, title, language, num_speakers) |
| `GET /api/meetings`, `GET /api/meetings/{id}` | list / detail + segments + summary |
| `GET /api/meetings/{id}/audio` | the recording (supports HTTP Range) |
| `GET /api/meetings/{id}/export?format=txt\|md\|srt` | download |
| `PATCH /api/meetings/{id}` | rename meeting / speakers |
| `POST /api/meetings/{id}/retranscribe` | re-run with the current engine |
| `POST /api/meetings/{id}/rediarize?num_speakers=N` | redo speaker labels only |
| `POST /api/meetings/{id}/resummarize` | regenerate the summary |
| `DELETE /api/meetings/{id}` | delete the meeting and its folder |

## 9. Known limitations

1. **Overlapping speech.** When two people talk at once, a single microphone
   records one mixed waveform. The transcriber hears one stream and gives the
   words to the dominant voice. No current system fully separates them from a
   single-mic recording — this affects local and cloud equally.
2. **Auto speaker count over-splits** on echoey rooms. Set the count when you
   know it.
3. **Cloud timestamps are reconstructed**, not measured — median ~2 s error.
   Local timestamps come straight from Whisper and are exact.
4. **Very distant/quiet voices** are boosted by speech normalization but can
   still be missed if barely audible to a human.
5. **NVIDIA only** for GPU acceleration (CUDA). AMD/Intel graphics run on CPU.
6. **No authentication** — see §7. Put it behind nginx before anyone else can
   reach it.
7. **One job at a time.** A single background worker processes the queue in
   order, so a 2-hour meeting blocks everything behind it. Fine for a team;
   it is not a multi-tenant service.
8. **Uploads are not scanned or limited in size** by the app. nginx should cap
   them (`client_max_body_size`).

## 10. Possible next steps

- Word-level highlighting during playback (Whisper can emit word timestamps).
- Speaker voice enrolment: name someone once, recognise them in future meetings.
- Action-item extraction into a checklist, with owners.
- Batch upload / watch-folder for a whole backlog of recordings.
- Real login (users/roles) if it ever outgrows nginx basic auth.
