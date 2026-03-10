#!/usr/bin/env bash
# Run the app using the project venv so dependencies (e.g. cryptography for PDF generation) are available.
set -e
cd "$(dirname "$0")"
./ensure_env.sh
exec .venv/bin/python app.py
