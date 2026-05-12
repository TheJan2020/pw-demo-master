#!/usr/bin/env bash
# Convenience runner. Creates a venv on first run, installs deps, starts the dev server.
set -euo pipefail

cd "$(dirname "$0")"

VENV=".venv"
if [ ! -d "$VENV" ]; then
  echo "Creating virtualenv at $VENV..."
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1090
source "$VENV/bin/activate"

pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

PORT="${PORT:-8080}"
echo "Starting PW Demo Master on http://localhost:$PORT"
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "$PORT" --reload
