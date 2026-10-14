#!/bin/sh
# User installation; no sudo, task-data removal, or autostart activation.
set -eu
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/linux-install.py" install "$@"
