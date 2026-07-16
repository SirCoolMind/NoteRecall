# Testing on Linux (WSL)

How to run this app on Linux from a Windows machine, to check the local engine
before deploying to a real server. Everything below was run and verified on
Ubuntu 24.04 (WSL2, Python 3.12).

---

## TL;DR — a copy is already set up

```powershell
wsl                          # open Ubuntu
cd ~/mt
PORT=8757 ./start.sh
```

Then open **<http://localhost:8757/setup>** in your normal Windows browser —
WSL forwards the port automatically. It's on port 8757 so it won't clash with
the Windows app on 8756 (both can run at once).

`~/mt` is configured for **CPU + whisper `base`** (fast, lower accuracy).
Change that at `/setup`, or edit `~/mt/config.json`.

Remove it any time with `rm -rf ~/mt` (2.9 GB).

---

## From scratch

### 1. One-time system packages

```bash
sudo apt update
sudo apt install -y python3-venv ffmpeg
```

Both are required. Without `python3-venv`, `python3 -m venv` fails with
*"ensurepip is not available"* — on Debian/Ubuntu it is a **separate package**
from `python3`.

### 2. Copy the app in

Don't run it from `/mnt/c/...` — the Windows `.venv` sits in that folder and
would collide with a Linux one, and `/mnt/c` is slow.

```bash
SRC="/mnt/c/Users/hafiz/Desktop/Playground/ai transcibe fable"
mkdir -p ~/mt && cd ~/mt
cp "$SRC"/*.py "$SRC"/requirements*.txt "$SRC/start.sh" .
cp -r "$SRC/static" .
chmod +x start.sh
```

Do **not** copy `config.json` — it holds your real Gemini API key.

### 3. Run

```bash
PORT=8757 ./start.sh
```

On first run `start.sh` will:
- create `.venv` and install `requirements.txt` (~487 MB, CPU-ready),
- install `requirements-gpu.txt` **only** if `nvidia-smi` finds a card,
- download the two speaker models (~165 MB) into `models/`,
- start the server.

### 4. Use it

| URL | what |
|---|---|
| <http://localhost:8757/> | the app — drop a recording in |
| <http://localhost:8757/setup> | requirements check (should say "Detected: Linux…") |
| <http://localhost:8757/about> | pipeline / tech stack |

To reach it from other machines on the LAN: `HOST=0.0.0.0 PORT=8757 ./start.sh`

---

## Gotchas found the hard way

**WSL is not a CPU-only machine.** It exposes the Windows NVIDIA driver, so
`nvidia-smi` works and CTranslate2 will happily use the GPU — even with no
`nvidia-*` pip packages installed. To honestly test the CPU path:

```bash
CUDA_VISIBLE_DEVICES="" PORT=8757 ./start.sh
```

You should see `[pipeline] CUDA unavailable (...); falling back to CPU` in the
log and `cpu (base)` on the Setup page. That is what a real CPU-only server does.

**Model size matters more than the platform.** On CPU, `base` transcribed 64 s
of audio in 16 s but misheard "Noted." as "No did." and "ringgit" as "ring it".
`large-v3` got both right. For a real CPU server use `medium` or better and
expect roughly realtime.

**Port clash.** Windows and WSL share `localhost`. If the Windows app holds
8756, Windows wins that port — always give WSL a different `PORT`.

**sudo needs your password** in WSL; there is no passwordless sudo configured.

---

## Quick health check

```bash
cd ~/mt
./.venv/bin/python - <<'PY'
import pipeline, server
pipeline._setup_cuda_dlls()          # Windows-only API must not be touched here
m, dev = pipeline.get_whisper()
print("device:", dev)
d = server.setup_check()
print("os:", d["os"], "|", d["os_detail"])
for c in d["checks"]:
    print(("OK  " if c["ok"] else "MISS"), c["name"], "-", c["detail"][:50])
PY
```

Measured on this WSL (20 cores, CPU-only, whisper `base`): a 64 s recording →
transcript + 2 speakers correctly separated in **16 s** (~4× realtime).
