#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
printf 'GPU preview: first recording, minutes 10–14. First use downloads Qwen weights.\n'
/usr/bin/caffeinate -i "$PROJECT_DIR/run.sh" preview \
  --input "$HOME/Downloads/Module 2" \
  --output "$PROJECT_DIR/../PreviewTranscripts-Qwen" \
  --model qwen3-asr-1.7b --timestamps --resume --keep-runtime --yes
printf '\nPreview succeeded. Starting the full GPU batch.\n'
exec /usr/bin/caffeinate -i "$PROJECT_DIR/run.sh" transcribe \
  --input "$HOME/Downloads/Module 2" \
  --input "$HOME/Downloads/Module 3" \
  --output "$PROJECT_DIR/../Transcripts" --model qwen3-asr-1.7b --timestamps --resume --yes
