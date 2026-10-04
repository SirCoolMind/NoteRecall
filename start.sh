#!/usr/bin/env bash
# NoteRecall - macOS / Linux launcher.
# Installs uv if missing, builds .venv, installs requirements, starts the
# server, and opens the browser once the server answers.
set -e
cd "$(dirname "$0")"

export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8756}"
URL="http://${HOST}:${PORT}"

echo "=== NoteRecall ==="

# 1. uv ------------------------------------------------------------------
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "[1/4] Installing uv (Python toolchain manager)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || {
    echo "ERROR: could not install uv. See https://docs.astral.sh/uv/ and retry."
    exit 1
  }
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || { echo "ERROR: uv installed but not found on PATH."; exit 1; }
else
  echo "[1/4] uv found."
fi

# 2. virtual environment (uv downloads Python itself if needed) -----------
PY=./.venv/bin/python
if [ ! -x "$PY" ]; then
  echo "[2/4] Creating Python 3.12 environment in .venv ..."
  uv venv --python 3.12 .venv
else
  echo "[2/4] Environment .venv found."
fi

# 3. dependencies (skipped when requirements are unchanged) --------------
HAS_GPU=0
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
  HAS_GPU=1
fi
STAMP=.venv/.requirements.stamp
NEW=.venv/.requirements.new
cat requirements.txt > "$NEW"
if [ "$HAS_GPU" = 1 ]; then cat requirements-gpu.txt >> "$NEW"; fi
if [ -f "$STAMP" ] && cmp -s "$STAMP" "$NEW"; then
  echo "[3/4] Dependencies up to date."
  rm -f "$NEW"
else
  echo "[3/4] Installing dependencies..."
  uv pip install --python "$PY" -r requirements.txt
  if [ "$HAS_GPU" = 1 ]; then
    echo "      NVIDIA GPU detected - adding CUDA libraries (~2.3 GB)..."
    uv pip install --python "$PY" -r requirements-gpu.txt
  else
    echo "      No NVIDIA GPU - skipping CUDA libraries (CPU mode)."
  fi
  mv "$NEW" "$STAMP"
fi

# Speaker-detection models (~165 MB), only fetched once.
if [ ! -f models/nemo_en_titanet_large.onnx ]; then
  echo "      Downloading speaker models..."
  mkdir -p models
  BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download
  curl -L -o models/nemo_en_titanet_large.onnx \
    "$BASE/speaker-recongition-models/nemo_en_titanet_large.onnx"
  curl -L -o models/seg.tar.bz2 \
    "$BASE/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
  tar -xjf models/seg.tar.bz2 -C models
  rm -f models/seg.tar.bz2
fi

# 4. start the server; open the browser once it responds -------------------
open_browser() {
  if command -v open >/dev/null 2>&1; then open "$URL"
  elif command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1
  else echo "Open $URL in your browser."; fi
}
(
  for _ in $(seq 1 300); do
    if curl -fsS -o /dev/null "$URL/api/status" 2>/dev/null; then
      open_browser
      exit 0
    fi
    sleep 1
  done
  echo "Server did not respond within 5 minutes; open $URL manually."
) &

echo "[4/4] Starting NoteRecall at $URL (Ctrl+C to stop)"
exec "$PY" server.py
