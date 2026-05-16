#!/usr/bin/env bash
# Start the WiFi-ATS dashboard (FastAPI + Vue static)
# Usage: ./start_dashboard.sh [port]

set -e
PORT=${1:-8080}
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "ERROR: .venv not found. Run bootstrap_testpc.sh first."
  exit 1
fi

echo "Starting WiFi-ATS dashboard on http://localhost:$PORT"
cd "$ROOT/dashboard"
exec "$VENV/bin/uvicorn" server:app --host 0.0.0.0 --port "$PORT" --reload
