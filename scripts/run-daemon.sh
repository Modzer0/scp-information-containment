#!/usr/bin/env bash
# Start the SCP daemon (long-running background service). Ctrl-C to stop.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

if [ -x ".venv/bin/python" ]; then
    VENV_PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
    VENV_PY=".venv/Scripts/python.exe"
else
    echo "error: .venv not found. run ./scripts/install.sh first." >&2
    exit 1
fi

exec "$VENV_PY" -m scp daemon
