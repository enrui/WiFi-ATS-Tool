#!/bin/sh
# bpi_iperf_server.sh — run on BPI-R4 to serve as iperf3 target
# Useful when testing the reverse direction (DUT as client)
#
# Usage:  bpi_iperf_server.sh [port]

PORT="${1:-5201}"

killall iperf3 2>/dev/null
sleep 0.5
iperf3 -s -p "$PORT" -D >/tmp/iperf3-server.log 2>&1

sleep 1
if netstat -ln 2>/dev/null | grep -q ":$PORT " || ss -ln 2>/dev/null | grep -q ":$PORT "; then
    echo "iperf3 server listening on :$PORT"
    exit 0
fi
echo "Failed to start iperf3 server" >&2
exit 1
