#!/usr/bin/env bash
# Run from project root: ensures venv, upgrades pip, installs deps, runs audit.
set -e
cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
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
echo "Environment ready. Run the app with: .venv/bin/python app.py"
