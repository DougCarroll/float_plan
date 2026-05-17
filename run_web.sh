#!/usr/bin/env bash
# Float Plan web — console: ensure .venv + web deps, then gunicorn (foreground).
# launchd: start-service.sh (same bootstrap).
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

# shellcheck source=scripts/ensure_venv.sh
source "$SCRIPT_DIR/scripts/ensure_venv.sh"

export FLASK_ENV=production
export PRODUCTION=true
if [ "$(uname)" = "Darwin" ]; then
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
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

echo "Starting Float Plan web app on port $PORT (foreground)..."
echo "Listen address: web.host in config.yaml and/or HOST in .env (see config.example.yaml)."
exec "$PY" -m gunicorn -c gunicorn_config.py web_app:app
