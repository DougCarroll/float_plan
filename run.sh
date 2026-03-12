#!/usr/bin/env bash
# Ensure the project venv is ready (creating it and installing deps if needed), then run the app.
set -e
cd "$(dirname "$0")"

# --- Begin ensure_env logic (inlined from ensure_env.sh) ---
# Recreate the venv if it's missing or broken (no Python binary).
if [[ ! -x .venv/bin/python ]]; then
  if [[ -d .venv ]]; then
    echo ".venv exists but has no Python binary; recreating..."
    rm -rf .venv
  fi

  echo "Creating virtual environment..."
  # Prefer Homebrew Python 3.12 on macOS so Tk is 8.6.13+ (fixes click issues)
  PYTHON=
  if [[ "$(uname -s)" == Darwin ]]; then
    BREW_PREFIX=
    for brew_cmd in brew /usr/local/bin/brew /opt/homebrew/bin/brew; do
      if command -v "$brew_cmd" &>/dev/null && BREW_PREFIX=$("$brew_cmd" --prefix 2>/dev/null); then
        [[ -n "$BREW_PREFIX" ]] && break
      fi
    done
    if [[ -n "$BREW_PREFIX" && -x "$BREW_PREFIX/opt/python@3.12/libexec/bin/python3.12" ]]; then
      PYTHON=$BREW_PREFIX/opt/python@3.12/libexec/bin/python3.12
    elif [[ -x "$BREW_PREFIX/bin/python3.12" ]]; then
      PYTHON=$BREW_PREFIX/bin/python3.12
    elif [[ -x /usr/local/opt/python@3.12/libexec/bin/python3.12 ]]; then
      PYTHON=/usr/local/opt/python@3.12/libexec/bin/python3.12
    elif [[ -x /usr/local/bin/python3.12 ]]; then
      PYTHON=/usr/local/bin/python3.12
    elif [[ -x /opt/homebrew/opt/python@3.12/libexec/bin/python3.12 ]]; then
      PYTHON=/opt/homebrew/opt/python@3.12/libexec/bin/python3.12
    elif [[ -x /opt/homebrew/bin/python3.12 ]]; then
      PYTHON=/opt/homebrew/bin/python3.12
    fi
  fi
  if [[ -z "$PYTHON" ]]; then
    PYTHON=python3
  fi
  echo "Using: $PYTHON"
  "$PYTHON" -m venv .venv
fi

echo "Upgrading pip..."
.venv/bin/python -m pip install --upgrade pip

echo "Installing dependencies from requirements.txt..."
.venv/bin/pip install -r requirements.txt

echo "Running pip audit..."
if .venv/bin/pip audit 2>/dev/null; then
  : # audit ran (exit 0 or reported issues)
else
  echo "Running pip check (dependency consistency)..."
  # Allow exit 1 so "X is not supported on this platform" (e.g. cffi wheel tags) doesn't block running the app
  .venv/bin/pip check || true
fi

echo ""
echo "Environment ready. Starting app..."
# --- End ensure_env logic ---

exec .venv/bin/python app.py
