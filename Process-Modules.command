#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec /usr/bin/caffeinate -i "$PROJECT_DIR/run.sh" transcribe \
  --input "$HOME/Downloads/Module 2" \
  --input "$HOME/Downloads/Module 3" \
  --output "$PROJECT_DIR/../Transcripts" --model whisper-large-v3 --timestamps --resume --yes
