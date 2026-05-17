#!/bin/bash
# launchd: .env, ensure .venv + requirements-web.txt, then gunicorn (use run_web.sh for console).
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export FLASK_ENV=production
export PRODUCTION=true
if [ "$(uname)" = "Darwin" ]; then
  export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
fi

_sk="${SECRET_KEY:-}"
if [ -z "$_sk" ] || [ "$_sk" = "change_this_secret_key" ]; then
  echo "ERROR: SECRET_KEY must be set for Float Plan when using start-service.sh (launchd)." >&2
  echo "Add to $SCRIPT_DIR/.env (this file is gitignored):" >&2
  echo "  SECRET_KEY=<long-random-hex>   # e.g. python3 -c \"import secrets; print(secrets.token_hex(32))\"" >&2
  echo "Then restart: launchctl kickstart -k \"gui/$(id -u)/com.svburnttoast.floatplan\"" >&2
  exit 1
fi

# shellcheck source=scripts/ensure_venv.sh
source "$SCRIPT_DIR/scripts/ensure_venv.sh"

exec "$PY" -m gunicorn -c gunicorn_config.py web_app:app
