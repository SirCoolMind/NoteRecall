# NoteRecall

Turn a meeting recording into a written transcript that says **who said what**,
plus a short summary. Built for meetings in **Bahasa Melayu, English, or both
mixed together** (bahasa rojak).

- **Private by default.** Everything runs on your own computer. Your recordings
  are not uploaded anywhere unless you choose the optional Google Gemini engine.
- **Free.** No account, no subscription.
- **Simple.** Drop a recording in, wait, download the transcript.

Project page: <https://github.com/SirCoolMind/NoteRecall>

Current version: **0.1.0** — see what changed in the [changelog](CHANGELOG.md). Your version is also shown in the app under **Settings (gear icon) → About**.

---

## Contents

1. [What you need](#1-what-you-need)
2. [Download NoteRecall](#2-download-noterecall)
3. [Start it](#3-start-it)
4. [Use it](#4-use-it)
5. [Start it again later, or stop it](#5-start-it-again-later-or-stop-it)
6. [Update to a newer version](#6-update-to-a-newer-version)
7. [Something went wrong?](#7-something-went-wrong)
8. [Remove NoteRecall](#8-remove-noterecall)
9. [Advanced: host it on a Linux server](#9-advanced-host-it-on-a-linux-server)
10. [For the curious: how it works](#10-for-the-curious-how-it-works)

---

## 1. What you need

| | |
|---|---|
| **Computer** | Windows 10 or 11, macOS, or Linux (e.g. Ubuntu) |
| **Free disk space** | About **6 GB** (the speech model alone is ~3 GB) |
| **Internet** | Only for the first start, to download the parts it needs |
| **Graphics card** | **Not needed.** An NVIDIA card makes it about twice as fast |

You do **not** need to install Python or anything else first. NoteRecall
installs what it needs on its first start.

---

## 2. Download NoteRecall

Pick **one** of the two ways below. If you are not sure, use **Way A**.

Both ways can **update from inside the app** later (see
[step 6](#6-update-to-a-newer-version)). Git is faster and more reliable, so we
recommend it; the ZIP needs nothing extra to download.

### Way A — Download with Git (recommended)

Git is a free tool that downloads the project and keeps it up to date. You only
paste a few lines.

**Windows** — open **Command Prompt** (press the Windows key, type `cmd`, press
Enter) and paste these lines one at a time:

```bat
winget install -e --id Git.Git
```

Close Command Prompt and open it again (so it finds Git), then:

```bat
cd %USERPROFILE%\Documents
```

```bat
git clone https://github.com/SirCoolMind/NoteRecall.git
```

**macOS** — open **Terminal** (press Cmd + Space, type `Terminal`, press Enter).
If macOS asks to install "command line developer tools", click **Install** and
wait for it to finish. Then:

```bash
cd ~/Documents
```

```bash
git clone https://github.com/SirCoolMind/NoteRecall.git
```

**Linux (Ubuntu / Debian)** — open **Terminal** (Ctrl + Alt + T):

```bash
sudo apt install -y git curl
```

```bash
cd ~/Documents
```

```bash
git clone https://github.com/SirCoolMind/NoteRecall.git
```

You now have a folder called **`NoteRecall`** inside your Documents folder.

### Way B — Download as a ZIP

No extra tools needed. If you install Git later, the first in-app update
connects the folder to GitHub by itself, so later updates are quick.

1. Open <https://github.com/SirCoolMind/NoteRecall> in your browser.
2. Click the green **`<> Code`** button, then **Download ZIP**.
3. Find the file `NoteRecall-main.zip` (usually in your **Downloads** folder).
4. Unzip it:
   - **Windows:** right-click the ZIP → **Extract All…** → **Extract**.
   - **macOS:** double-click the ZIP.
   - **Linux:** right-click → **Extract Here**.
5. You now have a folder called **`NoteRecall-main`**. Move it somewhere you
   will remember, for example your **Documents** folder.

---

## 3. Start it

The first start downloads about 1–3 GB, so it can take **10–30 minutes**
depending on your internet. Leave the window open. Later starts take a few
seconds.

### Windows

1. Open the NoteRecall folder (`NoteRecall` for Way A, `NoteRecall-main` for Way B).
2. Double-click **`start.bat`**.
3. If a blue **"Windows protected your PC"** box appears, click **More info**
   → **Run anyway**. (This appears because the file was downloaded from the
   internet.)
4. A black window opens and shows progress (`[1/4]` … `[4/4]`). When it is
   ready, your browser opens NoteRecall at <http://127.0.0.1:8756>.

**Keep the black window open** while you use NoteRecall. Closing it stops the app.

### macOS and Linux

Open **Terminal** and paste these two lines (change the folder name if yours
is different):

```bash
cd ~/Documents/NoteRecall
```

```bash
bash start.sh
```

If you used Way B (ZIP), the folder is `~/Documents/NoteRecall-main` instead:

```bash
cd ~/Documents/NoteRecall-main
```

When it is ready, your browser opens NoteRecall at <http://127.0.0.1:8756>.
If it doesn't open by itself, copy that address into your browser.

**Keep the Terminal window open** while you use NoteRecall.

### Finish setup inside the app

If anything is still missing, the Home screen shows a **Set up everything**
button above the upload area. Click it once and it installs the rest by itself,
showing progress for each item. You can also see this list anytime under
**Settings (gear icon) → Setup**.

---

## 4. Use it

1. **Drop your recording** on the big blue box, or click **Choose a recording**.
   mp3, wav, m4a, mp4 and ogg all work. 1–2 hour meetings are fine.
2. Optional: before dropping, pick the **Language** (Auto / BM / EN) and
   **Speakers** (how many people talked). Setting the real number of speakers
   gives much better results than Auto.
3. **Wait.** The list shows each stage and roughly how long is left. You can
   rename the meeting while it works. Expect about 25 minutes per hour of
   recording on a normal computer (about 13 with an NVIDIA graphics card).
4. **Open it** with the eye button when it shows **Ready**. Click a line to
   jump the audio there, click a speaker's name to rename them
   ("Speaker 1" → "Puan Aisyah").
5. **Download** the transcript as `.txt`, `.md` (with summary) or `.srt`
   (subtitles).

If the speakers look wrong (for example 40 speakers in a meeting of 5 people),
open the meeting and use **Re-detect with a fixed number**. It only redoes the
speaker labels, so it is quick.

---

## 5. Start it again later, or stop it

- **Start:** do the same as in [step 3](#3-start-it) — double-click
  `start.bat` (Windows) or run `bash start.sh` in the NoteRecall folder
  (macOS / Linux). It skips the downloads and opens in a few seconds.
- **Stop:** close the black window / Terminal window, or click inside it and
  press **Ctrl + C**.
- **Bookmark** <http://127.0.0.1:8756> in your browser. The bookmark only works
  while NoteRecall is running.

---

## 6. Update to a newer version

NoteRecall can update itself. Your meetings, settings and downloaded models are
kept. Works the same for both ways of downloading.

1. Click the **gear icon** (top right) to open **Settings**, then the
   **Updates** tab.
2. Click **Check for updates**. It says either **You're up to date** or which
   version is available, with a short list of what's new.
3. Click **Update now**. It shows each step, then **restarts itself** and the
   page reloads in the new version. This takes a minute or two.

NoteRecall also checks quietly about once a day. When a new version is out, a
small **Update available** note appears at the top of the screen; click it to
open the Updates tab. The version you have is shown under
**Settings → About** and at the top of the Updates tab.

The update waits if a recording is still being processed. If you have changed
NoteRecall's own files on this computer, it tells you so instead of
overwriting them.

If the page doesn't come back after a few minutes, close the NoteRecall window
and start it again with `start.bat` (Windows) or `bash start.sh` (macOS /
Linux).

### Updating by hand (if the in-app update doesn't work)

Your meetings live in the **`data`** folder and your settings in
**`config.json`**, both inside the NoteRecall folder.

**If you used Way A (Git):** stop NoteRecall, then in Command Prompt /
Terminal:

Windows:

```bat
cd %USERPROFILE%\Documents\NoteRecall
```

macOS / Linux:

```bash
cd ~/Documents/NoteRecall
```

Then (all systems):

```bash
git pull
```

Start NoteRecall again as usual. Your `data` folder and `config.json` are not
touched by `git pull`.

**If you used Way B (ZIP):**

1. Stop NoteRecall (close its window).
2. Download the new ZIP and unzip it, as in [step 2](#way-b--download-as-a-zip).
3. From your **old** NoteRecall folder, copy the **`data`** folder, the
   **`models`** folder and the **`config.json`** file into the **new** folder.
4. Start NoteRecall from the new folder. When everything looks right, delete
   the old folder.

---

## 7. Something went wrong?

| What you see | What to do |
|---|---|
| **"Windows protected your PC"** | Click **More info → Run anyway**. |
| The black window closes immediately | Open Command Prompt, paste `cd /d "C:\path\to\NoteRecall-main"` (your real folder path — you can drag the folder into the window to paste its path), press Enter, then type `start.bat` and press Enter. The window now stays open so you can read the error. |
| `bash: start.sh: No such file or directory` | You're in the wrong folder. Run `cd` to the folder that contains `start.sh` (see [step 3](#macos-and-linux)). Typing `ls` shows the files in the current folder. |
| `curl: command not found` (Linux) | Run `sudo apt install -y curl`, then start again. |
| Browser says **"This site can't be reached"** | NoteRecall isn't running yet, or its window was closed. Start it again and wait for `[4/4] Starting NoteRecall`. |
| Download stopped halfway on first start | Just start again. It continues from where it stopped. |
| Port **8756 already in use** | NoteRecall is probably already running in another window. Use that one, or close it first. |
| It is very slow | That's normal without an NVIDIA graphics card: about 25 minutes per hour of audio. You can keep using the computer, and you can close the browser tab — the work continues as long as the black/Terminal window is open. |
| Too many speakers detected | Open the meeting → **Re-detect with a fixed number** and choose how many people actually spoke. |

Still stuck? Open an issue at
<https://github.com/SirCoolMind/NoteRecall/issues> and paste the last lines from
the black/Terminal window.

---

## 8. Remove NoteRecall

1. Stop NoteRecall.
2. Delete the NoteRecall folder. **This also deletes your meetings** (they live
   in its `data` folder) — copy that folder somewhere first if you want to keep
   them.
3. Optional, to free ~3 GB more: delete the speech-model cache:
   - **Windows:** `C:\Users\<your name>\.cache\huggingface`
   - **macOS / Linux:** `~/.cache/huggingface` (a hidden folder in your home
     folder; in Finder press Cmd + Shift + . to show hidden folders)
4. Optional: remove the uv tool that NoteRecall installed —
   Windows: `C:\Users\<your name>\.local\bin\uv.exe`;
   macOS / Linux: `~/.local/bin/uv`.

---

## 9. Advanced: host it on a Linux server

For putting NoteRecall on an always-on Linux server that several people reach
through a web address, follow **[docs/deploy-nginx.md](docs/deploy-nginx.md)**.
It gives every file's exact location and copy-paste commands for: installing
the app in `/opt/noterecall`, the background service file
`/etc/systemd/system/noterecall.service`, the web server file
`/etc/nginx/sites-available/noterecall`, a password, HTTPS and the firewall.

> ⚠️ **NoteRecall has no login of its own.** Anyone who can open it can read
> every transcript, download the audio and delete meetings. Never expose it to
> the internet without the password step in that guide.

### Manual install (without the launcher)

For people who prefer to run each step themselves. Run these **inside the
NoteRecall folder** (see [step 3](#3-start-it) for how to get there):

```bash
# 1. install uv (see https://docs.astral.sh/uv/getting-started/installation/)
#    Windows:  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
#    macOS / Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12
uv pip install -r requirements.txt
uv pip install -r requirements-gpu.txt     # only with an NVIDIA graphics card
```

Then start the server:

- Windows: `.venv\Scripts\python.exe server.py`
- macOS / Linux: `.venv/bin/python server.py`

and open <http://127.0.0.1:8756>. Settings → Setup lists anything still
missing, each with copy-paste commands.

---

## 10. For the curious: how it works

### What it does

- **Transcribes** with Whisper `large-v3`, on an NVIDIA graphics card or the CPU
- **Identifies speakers** — rename "Speaker 1" once and it applies everywhere,
  including exports
- **Language**: auto-detect, or force Bahasa Melayu / English per recording
- **Player** that follows the transcript; click any line to jump there
- **Search** inside a transcript, and search all meetings by title or summary
- **Summary**: key points, frequent topics, speaking-time split
- **Export** as `.txt`, `.md` (with summary) or `.srt`
- **Re-transcribe** any meeting with the current engine, without uploading again

### Why `large-v3`

Smaller models don't just mishear bahasa rojak — they silently *translate* your
English into Malay, which reads fluently and is not what was said. Measured on
real meeting audio, CPU only:

| model | speed | "I'm the leader for the infrastructure" became |
|---|---|---|
| `base` | 5.5× realtime | "I'm Charles from Y&E… doing a four on the infrastructure" |
| `medium` | 3.7× realtime | "saya akan menulis tentang impran" — translated |
| **`large-v3`** | **2.5× realtime** | correct ✓ |

Details in [docs/summary.md §5](docs/summary.md).

### The cloud (Gemini) engine

Optional, under Settings → Transcription. It **uploads your audio to Google**
(kept ~48 hours), so don't use it for confidential meetings. You need your own
Gemini API key.

Gemini's own timestamps proved unusable, so NoteRecall uses only Gemini's words
and rebuilds the timing locally with voice-activity detection:

| approach | median timestamp error |
|---|---|
| Gemini's own timestamps | ~401 s |
| chunked + re-anchored | ~12 s |
| **text only + local timing (current)** | **~1.8 s** (max 7.4 s) |

Speakers in cloud mode still come from the local speaker detection.

### Better summaries (optional)

The built-in summary picks key sentences from the transcript. For a proper
AI-written summary in Malay/English, install [Ollama](https://ollama.com), then
in Command Prompt / Terminal:

```bash
ollama pull qwen2.5:7b
```

NoteRecall finds it automatically — open a meeting and choose **Regenerate
summary**.

### Where your files are

All inside the NoteRecall folder unless noted:

| | |
|---|---|
| `data/<meeting-id>/` | each meeting: audio, `transcript.json`, `summary.md`, `meta.json`. Deleting a meeting in the app deletes its folder. |
| `models/` | speaker-detection models (~165 MB) |
| `config.json` | your settings — **and your Gemini API key in plain text**. Never share or upload this file. |
| `.venv/` | the Python environment the launcher created |
| speech model (~3 GB) | outside the folder: `C:\Users\<you>\.cache\huggingface` (Windows) or `~/.cache/huggingface` (macOS / Linux), or wherever `HF_HOME` points |

### Speed

| | 1-hour meeting |
|---|---|
| NVIDIA RTX 4050 | ~13 min |
| CPU only (8 threads) | ~24 min, same accuracy |

More CPU threads is *slower*, not faster — the cap of 8 is deliberate, see
[docs/summary.md](docs/summary.md).

### Project files

| | |
|---|---|
| `start.bat` / `start.sh` | launchers (Windows / macOS + Linux) |
| `server.py` | web app, job queue, meetings, setup checks, exports |
| `installer.py` | the in-app **Set up everything** installer |
| `pipeline.py` | local engine: ffmpeg → Whisper → speaker detection → merge |
| `engines.py` | cloud engine: chunking, Gemini, timing |
| `summarizer.py` | Ollama or built-in summaries |
| `config.py` | reads and writes `config.json` |
| `static/` | the web interface (`index.html`, `css/`, `js/`, `i18n/` English + Malay, `fonts/`, `icons/`) |
| `requirements.txt` / `requirements-gpu.txt` | Python packages / extra NVIDIA packages |
| `docs/` | project summary, Linux server guide, WSL testing |
