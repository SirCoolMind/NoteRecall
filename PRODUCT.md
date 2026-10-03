# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One user: the owner, running NoteRecall on their own machine. They record their own meetings, held in Bahasa Melayu, English, or a mix of both (bahasa rojak, switching language mid-sentence), and use the app afterwards to get an accurate, speaker-labelled record of what was said. Their jobs: review what was said, find a moment again, check who said it, and take away a summary or an export.

## Product Purpose

NoteRecall turns long meeting recordings (1–2 hours) into accurate, speaker-labelled transcripts with summaries, running locally by default. It succeeds when the transcript says exactly what was said, in the language it was said in, with the right speaker on each line, and the user can move between audio and text without friction.

## Positioning

It is built for Malay/English code-switched speech and holds accuracy over convenience: it uses Whisper `large-v3` because smaller models silently *translate* rojak speech instead of transcribing it. It is local-first: audio never leaves the machine unless the user opts into the Gemini cloud engine. In cloud mode, timing is rebuilt locally from voice activity detection, because Gemini's own timestamps are unreliable.

## Operating Context

- Runs as a local web app at `http://localhost:8756` (FastAPI backend, static HTML pages in `static/`). It can also be self-hosted behind nginx, but the app has no login of its own.
- One page at `/`: the Home schedule with the drop slot and readiness panel, the meeting view (`#/m/<id>`), and the Settings drawer (engine, defaults, setup checks with one-click install, about). `/setup` and `/about` redirect into the drawer.
- Typical session: upload a recording → wait for processing (live status and progress) → review the transcript with the speaker-ribbon player synced to it → rename speakers → read the summary → export.
- Processing a 1-hour meeting takes ~13 min on GPU and ~24 min on CPU, so waiting for a job to finish is a real part of using it.

## Capabilities and Constraints

- Upload mp3/wav/m4a/mp4/ogg; transcribe with Whisper `large-v3` (GPU or CPU); diarization with editable speaker names that apply everywhere; force Malay or English per upload, or auto-detect it; set the speaker count, or re-detect speakers afterwards; re-transcribe without re-uploading; search within a transcript; summary tab (key points, topics, speaking-time split; AI summary through Ollama when installed); export `.txt` / `.md` / `.srt`.
- **Local-first and private.** Audio stays on the machine by default. The cloud engine stays opt-in, and the UI must keep saying plainly that it uploads audio to Google.
- **Works offline.** No CDN fonts, scripts, or other remote assets; everything is served locally.
- **Bilingual UI (Bahasa Melayu + English).** The interface itself must be available in both languages, not just the transcripts. Built: `static/i18n/en.json` and `ms.json`.
- No build step: plain HTML/CSS/ES modules with vendored Alpine.js, served by FastAPI (ADR 0001).
- Destructive actions are real: deleting a meeting permanently removes its folder (audio, transcript, summary).
- Terminology: "meeting", "transcript", "speaker", "summary", "engine" (local / Gemini), "re-transcribe", "re-detect speakers".

## Brand Commitments

- Name: **NoteRecall** (formerly the working title "Meeting Transcriber").
- Voice: plain, direct, and honest about tradeoffs, as in the README: measured numbers, explicit warnings, no hype.

## Evidence on Hand

- Measured model comparison and timestamp-accuracy figures in `README.md` and `docs/summary.md` (e.g. cloud timestamps went from ~401 s median error to ~1.8 s once timing was rebuilt locally).
- Real meeting data lives in `data/<meeting-id>/`. It is private and must never be used as public sample content.
- No testimonials, users, or press. Don't invent any.

## Product Principles

1. **What was said, exactly.** Transcript fidelity, including language and speaker, outranks speed and polish.
2. **Private by default.** Anything that sends data off the machine is opt-in, clearly labelled, and reversible.
3. **Audio and text are one record.** Moving between listening and reading should feel instant and stay in sync.
4. **Honest about the machine.** Show real progress, real requirements, and real tradeoffs; never hide a slow step or a failure.
5. **Both languages are first-class.** Malay and English are equal in transcripts and in the interface.
