#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [ "${1:-}" = "--dev" ]; then
  .venv/bin/python -m pip install -e '.[dev]'
else
  .venv/bin/python -m pip install -e .
fi
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo 'Install FFmpeg (includes ffprobe): macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt-get install ffmpeg' >&2
  exit 1
fi
printf '%s\n' 'Ready. Run .venv/bin/reelreveal --help. Identification also requires Ollama and an image-capable model.'
