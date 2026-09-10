#!/usr/bin/env bash
# Fetch the default Turkish Piper voice into data/voices (not committed; ~63 MB).
# faster-whisper downloads its own model on first start (HF cache).
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p data/voices && cd data/voices
for f in tr_TR-dfki-medium.onnx tr_TR-dfki-medium.onnx.json; do
  [ -f "$f" ] || curl -fL -o "$f" "https://huggingface.co/rhasspy/piper-voices/resolve/main/tr/tr_TR/dfki/medium/$f"
done
ls -la
