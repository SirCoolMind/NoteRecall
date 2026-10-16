# Spec: Optional Nemotron-3 speaker detection (experimental)

Status: agreed in grilling session, 2026-10-04. Built 2026-10-04..06 on an unpushed
branch that was lost with its folder; rebuilt 2026-10-16 from the session transcript.
One deliberate change since: Nemotron runs in a worker process (see `nemo_diar.diarize`),
because PyTorch's CUDA 13 cuDNN and the CUDA 12 one used by Whisper and the GPU
build of sherpa-onnx cannot share a process.

## What and why

Add [nvidia/Nemotron-3-Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization)
as an **optional, experimental** speaker-detection (diarization) backend, to see
whether it labels speakers better than today's diarizer. Motivation: curiosity
about new tech, not a known defect.

**Scope is speakers only.** Whisper still produces all transcript text; this
only changes who each line is attributed to.

| Step | Today | With toggle on |
|---|---|---|
| Speech to text | Whisper large-v3 | unchanged |
| Diarization | sherpa-onnx: pyannote seg + NeMo TitaNet ("Standard") | Nemotron-3-Diarization |

Model facts (from model card): Sortformer-style streaming, 100M params,
**max 8 speakers**, needs NeMo Framework 3.0 + PyTorch, Python 3.12+ (venv is
3.12), tuned for NVIDIA GPUs, Linux preferred. Training languages exclude
Malay — part of the experiment. License OpenMDW v1.1 (use permitted).

## Ground rule: additive only (Q2)

- Toggle **off** (default) = behaviour identical to today.
- No existing function signature changes.
- All existing tests pass untouched.
- New code lives in a new module (e.g. `nemo_diar.py`); existing files get only
  minimal hooks (dispatch in `pipeline.diarize()`, one config key, installer
  step, settings UI, i18n, README).

## Decisions

| # | Decision |
|---|---|
| Q1 | Model: `nvidia/Nemotron-3-Diarization`. |
| Q4/Q9 | **Soft gate.** Toggle always usable. Warn when no NVIDIA CUDA GPU, or VRAM < 4 GB ("may be very slow or fail"). One confirm click, not repeated. No RAM check. |
| Q5/Q13 | Not installed by first-run `start.bat`/`start.sh`. Separate `requirements-nemo.txt`. Optional item in Settings → Setup; required only when toggle on. Turning toggle on while not installed shows "Install now (~X GB)" using the existing `installer.py` runner. Turning off never uninstalls. |
| Q6 | Applies everywhere `diarize()` is used: local engine, Gemini engine, Re-detect. |
| Q7 | Windows + Linux best-effort; macOS CPU-only with "may be slow" warning. Install/import failure shown in Setup; toggle stays usable and falls back (Q16). |
| Q8 | Switch lives in Settings → **Speakers** tab: field "Speaker detection model" — **Standard** / **Nemotron-3 (experimental)**. Config key e.g. `diarizer: "standard" \| "nemotron"`, default `"standard"`. |
| Q10 | Fixed speaker count > 8 → that job uses Standard, with a note. Auto → Nemotron (caps at 8). |
| Q11 | PyTorch build auto-picked via existing NVIDIA detection: CUDA build (~2.5 GB) with GPU, CPU build (~200 MB) without. |
| Q12 | Model weights stored in app `models/` folder, not the Hugging Face user cache. |
| Q14 | Record diarizer used per meeting in existing `speakers_by` metadata field. Comparison workflow: flip toggle → **Re-detect speakers** on same meeting (text unchanged). |
| Q16 | Runtime failure (OOM, import error, etc.) → job automatically falls back to Standard and completes. Metadata notes "Nemotron failed, used Standard". Toggle stays on. |
| Q17 | Meeting screen shows one small line "Speakers by: …" (details/speakers popover), only when the field exists — old meetings look unchanged. |
| Q18 | All new strings in both `static/i18n/en.json` and `ms.json`. |
| Q19 | README: new subsection under §10 "Optional: Nemotron-3 speaker detection (experimental)" (speakers only, 8-speaker cap, Malay not in training data, GPU recommended, disk size, how to enable, compare via Re-detect). Add row to §1 disk table; add §7 troubleshooting line about automatic fallback. |

## Done when (Q20)

1. Toggle off: no behaviour change; all existing tests pass unchanged.
2. New unit tests (fakes only, no real downloads) cover: dispatch, >8 fallback,
   error fallback, warning/gate check.
3. Manual check on a real PC: toggle on → Install → Re-detect on a real meeting
   shows "Speakers by: Nemotron-3".
4. README and both i18n files updated.

## Out of scope

- Replacing Whisper / alternative speech-to-text models (Parakeet/Canary) —
  separate grilling if wanted.
- Uninstalling NeMo/PyTorch when the toggle is turned off.

## Implementation plan

Findings that shape the plan:
- Settings → Speakers already has a "Speaker detection model" section
  (`static/index.html` `#set-spkmodel`) listing one model with an "Active"
  pill. The new choice goes into that list.
- Speaker count is capped at 8 in the UI and `/api/config`, so the Q10 ">8"
  fallback can only be hit via the raw `/rediarize?num_speakers=` API. Keep the
  guard, it's cheap.
- `speakers_by` already exists but means something else for Gemini
  ("gemini (per chunk)" vs "local diarization"). **Deviation from Q14:** use a
  new meta field `diarizer` (`"standard"`, `"nemotron"`,
  `"standard (nemotron failed)"`) instead of overloading `speakers_by`.
- Setup checks use `req` = `always | local | gemini | optional`, and one-click
  install only picks `always` + current engine. Nemotron checks report
  `req="always"` when the toggle is on, else `"optional"`, so the installer
  logic stays unchanged.

### Step 0: Spike (do first, throwaway, on the real PC)
Verify before building, because the model card is silent on these:
1. Exact pip package for NeMo 3.0 ASR/speech on Windows + Python 3.12, and
   whether it installs at all.
2. Repo file layout (`.nemo` vs safetensors) and loading from a local dir
   (`snapshot_download(local_dir=models/nemotron-3-diarization)` + restore).
3. `diarize()` output format and the chunked/streaming settings needed for a
   1-hour meeting without running out of memory.
4. Real install size (CUDA vs CPU torch) for the "Install now (~X GB)" text.
If step 1 fails on Windows, stop and revisit Q7 before step 1 below.

### Step 1: Backend module (new file `nemo_diar.py`)
- `is_installed()`, `model_present()`, `MODEL_DIR` (under `pipeline.MODELS_DIR`).
- `diarize(audio, num_speakers, progress_cb) -> [(start, end, spk)]`, with the
  same contract as `pipeline.diarize`. Lazy imports; cache the loaded model.
- `gate(cuda_count, vram_mb, os_name) -> {"ok": bool, "reasons": [...]}`, a pure
  function (no GPU → warn; VRAM < 4096 → warn; macOS → CPU warning).
  VRAM read from `nvidia-smi --query-gpu=memory.total`, failure → unknown.

### Step 2: Hooks in existing code (minimal)
- `config.py`: DEFAULTS `"diarizer": "standard"`. `config.example.json`: doc line.
- `server.set_config`: accept `diarizer in ("standard", "nemotron")`.
- `pipeline.py`: new `diarize_labeled(audio, n, cb) -> (turns, label)` that
  picks Nemotron when configured and n ≤ 8, and catches any error → Standard
  with label `"standard (nemotron failed)"`. `diarize()` keeps its signature
  and just returns turns. `run_job`/`rediarize_job` add a `diarizer` key to
  their result dicts. `engines.py` Gemini path uses `diarize_labeled` too.
- `server.worker`: copy `result["diarizer"]` into meta for both job kinds.
- `server._evaluate`: two checks, `nemo_toolkit` and `nemotron_model`, req
  as above; plus a `diarizer_gate` field in the response for the UI.
- `installer.py`: steps `nemo_toolkit` (torch CUDA/CPU build picked by the
  existing CUDA check, then `-r requirements-nemo.txt`) and `nemotron_model`
  (snapshot download to `models/`). Append to ORDER; DEPENDS
  `nemotron_model → nemo_toolkit`.
- New `requirements-nemo.txt`.

### Step 3: UI
- Speakers tab `#set-spkmodel`: two choices (Standard / Nemotron-3
  experimental), same radio pattern as the Device section, with its own save state.
- Picking Nemotron: if gate not ok → inline warning with reasons + "Use
  anyway" (one click, then saved; not asked again while selected). If not
  installed → "Install now (~X GB)" calling `/api/setup/install` with
  `["nemo_toolkit", "nemotron_model"]` and showing progress.
- Meeting speakers popover: one line "Speakers by: …" only when
  `meta.diarizer` exists.
- i18n keys in `en.json` + `ms.json`.

### Step 4: Tests (fakes only)
- New `tests/test_nemo_diar.py`: gate cases; dispatch picks Nemotron when
  configured; n > 8 → Standard; Nemotron raising → Standard + failed label;
  toggle off → Nemotron never imported.
- `test_settings.py`-style round trip for `diarizer` (new test, existing ones untouched).
- `test_setup_install.py`-style: new checks report req `always` only when toggle on.
- Full existing suite passes unchanged.

### Step 5: README
§1 disk row, §7 troubleshooting line, §10 subsection (per Q19).

### Step 6: Manual check (Done #3) on your PC.
