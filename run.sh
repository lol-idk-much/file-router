#!/usr/bin/env bash
# FileRouter launcher script
set -euo pipefail

# Resolve symlinks to find the actual directory of run.sh
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SOURCE="${BASH_SOURCE[0]}"
elif [ -n "${(%):-%N:-}" ]; then
  SOURCE="${(%):-%N}"
else
  SOURCE="$0"
fi
while [ -h "$SOURCE" ]; do
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE"
done
SCRIPT_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null 2>&1 && pwd )"

# Prefer local virtual environment if present
if [ -f "$SCRIPT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$SCRIPT_DIR/.venv/bin/python3"
elif [ -f "$HOME/.local/bin/python3" ]; then
    PYTHON_BIN="$HOME/.local/bin/python3"
else
    PYTHON_BIN="$(which python3)"
fi

if [ $# -eq 0 ]; then
    set -- "--run"
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/router.py" "$@"
