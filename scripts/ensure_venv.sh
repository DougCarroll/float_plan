#!/bin/bash
# Create/repair .venv and install web dependencies for Float Plan.
# Sourced by run_web.sh and start-service.sh after cd "$SCRIPT_DIR" and loading .env.
set -e
: "${SCRIPT_DIR:?ensure_venv: SCRIPT_DIR must be set}"
cd "$SCRIPT_DIR"

VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv}"
if [ ! -x "$VENV_DIR/bin/python" ] && [ ! -x "$VENV_DIR/bin/python3" ]; then
  if [ -d "$VENV_DIR" ]; then
    echo "Removing incomplete venv at $VENV_DIR (missing bin/python)"
    rm -rf "$VENV_DIR"
  fi
  echo "Creating virtual environment at $VENV_DIR..."
  python3 -m venv "$VENV_DIR"
fi
PY="$VENV_DIR/bin/python"
if [ ! -x "$PY" ]; then
  PY="$VENV_DIR/bin/python3"
fi
if [ ! -x "$PY" ]; then
  echo "ERROR: venv has no usable Python under $VENV_DIR/bin/." >&2
  exit 1
fi

echo "Using venv: $VENV_DIR (installing / refreshing web dependencies)"
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -q -r requirements-web.txt

export PY
export VENV_DIR
