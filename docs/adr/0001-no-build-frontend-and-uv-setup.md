# 1. No-build frontend with Alpine.js, and uv-based one-step setup

- Status: accepted
- Date: 2026-10-03

## Context

NoteRecall is meant to be set up by anyone on their own machine with as little
friction as possible, which is why `start.bat` / `start.sh` exist. The UI is
being redesigned (bilingual BM/EN, larger type, fewer clicks, settings
reachable from anywhere, one-click setup), and it must work offline.

Today:

- each page in `static/` carries its own copy of the CSS, and the copies have
  drifted (`--accent` vs `--blue`, `#ff5d5d` vs `#ff6b6b`);
- `start.bat` assumes `.venv` already exists, so a fresh Windows machine
  cannot start the app from the launcher;
- ffmpeg is a manual system install, and `pipeline.py` hard-codes one
  developer's ffmpeg path.

## Decision

1. **Frontend stays build-free.** FastAPI serves static HTML. Shared design
   tokens live in one `static/css/tokens.css`; behaviour is ES modules plus
   **Alpine.js vendored into the repo** (no CDN). UI strings come from
   `static/i18n/en.json` and `static/i18n/ms.json`. The first-launch language
   follows the browser, with a toggle that is remembered.
2. **Setup is one step on every OS.** `start.bat` / `start.sh` install
   [uv](https://docs.astral.sh/uv/) if it is missing, then let uv provide
   Python and the dependencies and run the server. Nobody needs Python
   pre-installed.
3. **ffmpeg ships as a pip dependency** (`imageio-ffmpeg`) instead of a
   system install. Duration probing must not depend on `ffprobe`, which that
   package does not include.
4. **Installs run from the app.** The setup checks in `server.py` gain a
   one-click "Set up everything" path that runs the known fixes with
   progress; the manual per-OS instructions remain as the fallback.

## Consequences

- Python is the only runtime anyone needs; no Node toolchain, for users or for
  people editing the UI.
- Without a build step there is no component compiler: reuse comes from
  shared CSS classes, Alpine components, and small ES modules. If the UI ever
  grows past a handful of screens, revisit this (Svelte + Vite with committed
  build output was the runner-up).
- The launchers download uv on first run, which needs internet once; after
  setup the app works fully offline.
