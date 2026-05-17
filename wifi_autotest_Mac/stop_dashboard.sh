#!/usr/bin/env bash
# Stop the WiFi-ATS dashboard started by start_dashboard.sh

PIDFILE="/tmp/wifi_ats_dashboard.pid"

if [[ ! -f "$PIDFILE" ]]; then
  echo "Dashboard is not running (no PID file found)."
  exit 0
fi

PID=$(cat "$PIDFILE")
if kill -0 "$PID" 2>/dev/null; then
  kill "$PID"
  rm -f "$PIDFILE"
  echo "Dashboard stopped (PID $PID)."
else
  echo "Process $PID not found — already stopped."
  rm -f "$PIDFILE"
fi
