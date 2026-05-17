#!/usr/bin/env bash
# Start the WiFi-ATS dashboard in the background.
# Usage: ./start_dashboard.sh [port]
#   PID is written to /tmp/wifi_ats_dashboard.pid
#   Logs go to /tmp/wifi_ats_dashboard.log

PORT=${1:-8080}
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"
PIDFILE="/tmp/wifi_ats_dashboard.pid"
LOGFILE="/tmp/wifi_ats_dashboard.log"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "ERROR: .venv not found. Run bootstrap_testpc.sh first."
  exit 1
fi

# Check if already running
if [[ -f "$PIDFILE" ]]; then
  OLD_PID=$(cat "$PIDFILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Dashboard already running (PID $OLD_PID)  →  http://localhost:$PORT"
    exit 0
  fi
  rm -f "$PIDFILE"
fi

cd "$ROOT/dashboard"
nohup "$VENV/bin/uvicorn" server:app \
  --host 0.0.0.0 --port "$PORT" --reload \
  >> "$LOGFILE" 2>&1 &

echo $! > "$PIDFILE"
echo "Dashboard started (PID $!)  →  http://localhost:$PORT"
echo "Log: $LOGFILE"
