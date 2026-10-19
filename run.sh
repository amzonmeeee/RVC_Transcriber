#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
if ! command -v python3 >/dev/null 2>&1; then
  echo 'This release needs an existing Python 3.9+ for its small stdlib supervisor. No packages are installed into it. Inference uses a disposable managed Python.' >&2
  exit 2
fi
exec python3 -B "$PROJECT_DIR/launcher.py" "$@"
