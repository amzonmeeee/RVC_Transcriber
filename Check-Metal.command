#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
"$PROJECT_DIR/run.sh" doctor
printf '\nPress Enter to close. '
read -r ignored
