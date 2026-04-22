#!/usr/bin/env bash
# SCP: Information Containment — Linux / macOS installer
# Creates .venv, installs dependencies, verifies the install.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_DIR"

# ---- find a usable Python ---------------------------------------------
find_python() {
    for candidate in python3.14 python3.13 python3.12 python3.11 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            if "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PY=$(find_python) || {
    echo "error: Python 3.11+ not found on PATH" >&2
    echo "       install from https://www.python.org/ (macOS: 'brew install python')" >&2
    exit 1
}
echo "using $PY ($("$PY" --version))"

# ---- venv -------------------------------------------------------------
if [ ! -d ".venv" ]; then
    echo "creating virtual env at .venv/"
    "$PY" -m venv .venv
else
    echo "reusing existing .venv/"
fi

# Python's venv layout differs: Unix → .venv/bin/python, Windows → .venv/Scripts/python.exe
if [ -x ".venv/bin/python" ]; then
    VENV_PY=".venv/bin/python"
elif [ -x ".venv/Scripts/python.exe" ]; then
    VENV_PY=".venv/Scripts/python.exe"
else
    echo "error: venv python not found (.venv/bin/python or .venv/Scripts/python.exe)" >&2
    exit 1
fi

# ---- install ----------------------------------------------------------
echo "upgrading pip..."
"$VENV_PY" -m pip install --upgrade --quiet pip

echo "installing scp-information-containment (editable)..."
"$VENV_PY" -m pip install -e . --quiet

# ---- verify -----------------------------------------------------------
echo "verifying imports..."
"$VENV_PY" -c "from scp.daemon.main import Daemon; from scp.tui.main import ScpTui; print('ok')"

echo
echo "install complete."
echo "next steps:"
echo "  1) start the daemon:    ./scripts/run-daemon.sh"
echo "  2) in another terminal: ./scripts/run-tui.sh"
echo "  3) inside the TUI type: help"
