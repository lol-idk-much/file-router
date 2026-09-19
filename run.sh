#!/usr/bin/env bash
# FileRouter launcher script
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer local virtual environment if present
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif [ -f "$HOME/.local/bin/python3" ]; then
    PYTHON_BIN="$HOME/.local/bin/python3"
else
    PYTHON_BIN="$(which python3)"
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/router.py" --run "$@"
