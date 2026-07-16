#!/usr/bin/env bash
# Meeting Transcriber — Linux / macOS launcher
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "Creating virtual environment..."
  # Debian/Ubuntu: needs the separate python3-venv package, else this fails
  # with "ensurepip is not available"
  python3 -m venv .venv || {
    echo "ERROR: could not create the venv. On Debian/Ubuntu run:"
    echo "  sudo apt install -y python3-venv"
    exit 1
  }
  ./.venv/bin/pip install --upgrade pip -q
  ./.venv/bin/pip install -r requirements.txt
  # only pull the 2.3 GB of CUDA libraries when there is actually an NVIDIA GPU
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then
    echo "NVIDIA GPU detected — installing CUDA libraries..."
    ./.venv/bin/pip install -r requirements-gpu.txt
  else
    echo "No NVIDIA GPU — skipping CUDA libraries (CPU mode)."
    echo "Tip: pick a smaller Whisper model at http://localhost:8756/setup"
  fi
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg not found. Install it first:"
  echo "  Debian/Ubuntu : sudo apt install -y ffmpeg"
  echo "  Fedora/RHEL   : sudo dnf install -y ffmpeg"
  echo "  Arch          : sudo pacman -S ffmpeg"
  echo "  macOS         : brew install ffmpeg"
  exit 1
fi

# Speaker-detection models (~165 MB), only fetched once.
if [ ! -f models/nemo_en_titanet_large.onnx ]; then
  echo "Downloading speaker models..."
  mkdir -p models
  BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download
  curl -L -o models/nemo_en_titanet_large.onnx \
    "$BASE/speaker-recongition-models/nemo_en_titanet_large.onnx"
  curl -L -o models/seg.tar.bz2 \
    "$BASE/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
  tar -xjf models/seg.tar.bz2 -C models
  rm -f models/seg.tar.bz2
fi

# export, so server.py actually sees these and the URL printed here is the truth
export HOST="${HOST:-127.0.0.1}"
export PORT="${PORT:-8756}"
echo "Meeting Transcriber -> http://${HOST}:${PORT}"
exec ./.venv/bin/python server.py
