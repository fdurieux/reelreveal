#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
dev=0
skip_vision=0
model="${OLLAMA_MODEL:-gemma3:4b}"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dev) dev=1; shift ;;
    --skip-vision) skip_vision=1; shift ;;
    --model)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        echo '--model requires an image-capable Ollama model name.' >&2
        exit 2
      fi
      model="$2"; shift 2 ;;
    -h|--help)
      echo 'Usage: ./scripts/install.sh [--dev] [--skip-vision] [--model NAME]'
      echo 'Installs ReelReveal, Ollama (if missing), and gemma3:4b by default.'
      echo 'OLLAMA_MODEL sets the model default. --skip-vision skips all Ollama operations.'
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo 'Install FFmpeg (includes ffprobe): macOS: brew install ffmpeg; Debian/Ubuntu: sudo apt-get install ffmpeg' >&2
  exit 1
fi
"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --upgrade pip
if [ "$dev" -eq 1 ]; then
  .venv/bin/python -m pip install -e '.[dev]'
else
  .venv/bin/python -m pip install -e .
fi
if [ "$skip_vision" -eq 0 ]; then
  .venv/bin/python -m reelreveal.setup_vision --model "$model"
else
  echo 'Vision setup skipped. Use --provider none for extraction, or configure Ollama separately.'
fi
printf '%s\n' 'Ready. Run .venv/bin/reelreveal --help.'
