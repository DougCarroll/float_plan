#!/bin/bash
# Minimal startup for launchd service: no pip/audit, just env + gunicorn.
# Requires: .env with SECRET_KEY=... (or SECRET_KEY in launchd environment).
# Run run_web.sh once to create .venv and install deps before enabling the service.

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load SECRET_KEY and optional overrides from .env
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

export FLASK_ENV=production
export PRODUCTION=true
if [ "$(uname)" = "Darwin" ]; then
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
fi

# Match web_app.py: production requires SECRET_KEY (no data/.flask_secret fallback).
_sk="${SECRET_KEY:-}"
if [ -z "$_sk" ] || [ "$_sk" = "change_this_secret_key" ]; then
  echo "ERROR: SECRET_KEY must be set for Float Plan when using start-service.sh (launchd)." >&2
  echo "Add to $SCRIPT_DIR/.env (this file is gitignored):" >&2
  echo "  SECRET_KEY=<long-random-hex>   # e.g. python3 -c \"import secrets; print(secrets.token_hex(32))\"" >&2
  echo "Then restart: launchctl kickstart -k \"gui/$(id -u)/com.svburnttoast.floatplan\"" >&2
  exit 1
fi

VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv}"
PY="$VENV_DIR/bin/python"
if [ ! -x "$PY" ]; then
  PY="$VENV_DIR/bin/python3"
fi

if [ ! -x "$PY" ]; then
  echo "Error: venv not found at $VENV_DIR. Run ./run_web.sh once to create it." >&2
  exit 1
fi

if ! "$PY" -c "import gunicorn" 2>/dev/null; then
  echo "Error: gunicorn is not installed in venv. Run ./run_web.sh once." >&2
  exit 1
fi

exec "$PY" -m gunicorn -c gunicorn_config.py web_app:app
