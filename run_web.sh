#!/usr/bin/env bash
# Run Float Plan web app (for use behind Cloudflare tunnel, like anchor_watch).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load SECRET_KEY and optional overrides from .env (same as start-service.sh)
if [ -f .env ]; then
  set -a
  source .env
  set +a
fi

VENV_DIR="${VENV_DIR:-$SCRIPT_DIR/.venv}"
if [ ! -x "$VENV_DIR/bin/python" ] && [ ! -x "$VENV_DIR/bin/python3" ]; then
  if [ -d "$VENV_DIR" ]; then
    echo "Removing incomplete venv at $VENV_DIR (missing bin/python)"
    rm -rf "$VENV_DIR"
  fi
  echo "No venv at $VENV_DIR. Create one with: ./run.sh (then run this again)."
  exit 1
fi
PY="$VENV_DIR/bin/python"
if [ ! -x "$PY" ]; then
  PY="$VENV_DIR/bin/python3"
fi
if [ ! -x "$PY" ]; then
  echo "ERROR: venv has no usable Python under $VENV_DIR/bin/. Run ./run.sh" >&2
  exit 1
fi

# Port from config.yaml (web.port) or env (default 5503)
if [ -f config.yaml ] && "$PY" -c "import yaml" 2>/dev/null; then
  PORT_FROM_CONFIG=$("$PY" -c "
import yaml
try:
    with open('config.yaml') as f:
        c = yaml.safe_load(f)
    print((c.get('web') or {}).get('port', 5503))
except Exception:
    print(5503)
" 2>/dev/null) || true
  export PORT="${PORT:-${PORT_FROM_CONFIG:-5503}}"
else
  export PORT="${PORT:-5503}"
fi

echo "Installing web dependencies..."
"$PY" -m pip install -q -r requirements-web.txt

echo "Starting Float Plan web app on port $PORT..."
echo "Listen address: web.host in config.yaml and/or HOST in .env (see config.example.yaml)."
echo "Cloudflared on this machine can still use http://127.0.0.1:$PORT when the app binds 0.0.0.0."
exec "$PY" -m gunicorn -c gunicorn_config.py web_app:app
