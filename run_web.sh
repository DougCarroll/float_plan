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
if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "No venv at $VENV_DIR. Create one with: ./run.sh (then run this again)."
  exit 1
fi
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"

# Port from config.yaml (web.port) or env (default 5000)
if [ -f config.yaml ] && "$PY" -c "import yaml" 2>/dev/null; then
  PORT_FROM_CONFIG=$("$PY" -c "
import yaml
try:
    with open('config.yaml') as f:
        c = yaml.safe_load(f)
    print((c.get('web') or {}).get('port', 5000))
except Exception:
    print(5000)
" 2>/dev/null) || true
  export PORT="${PORT:-${PORT_FROM_CONFIG:-5000}}"
else
  export PORT="${PORT:-5000}"
fi

echo "Installing web dependencies..."
"$PIP" install -q -r requirements-web.txt

echo "Starting Float Plan web app on port $PORT..."
echo "Point Cloudflare tunnel at http://127.0.0.1:$PORT (or use HOST=0.0.0.0 for direct access)."
exec "$PY" -m gunicorn -c gunicorn_config.py web_app:app
