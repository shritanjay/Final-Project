#!/usr/bin/env bash
# One-command start (macOS / Linux): ./run.sh   then open http://localhost:8000
set -e
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
if [ ! -d .venv ]; then
  echo "Creating virtual environment…"
  "$PY" -m venv .venv
fi
echo "Installing packages (first run takes ~1 minute)…"
.venv/bin/pip install -q --disable-pip-version-check -r requirements.txt
if [ ! -f .env ] && [ ! -f ../.env ]; then
  echo "WARNING: no .env found here or one folder up. Copy .env.example to .env and add PORTKEY_API_KEY."
fi
echo ""
echo "Career Scout is starting at http://localhost:8000  (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
