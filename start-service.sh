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

VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv}"
PY="$VENV_DIR/bin/python"

if [ ! -x "$PY" ]; then
  echo "Error: venv not found at $VENV_DIR. Run ./run_web.sh once to create it." >&2
  exit 1
fi

exec "$PY" -m gunicorn -c gunicorn_config.py web_app:app
