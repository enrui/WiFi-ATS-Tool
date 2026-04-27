#!/usr/bin/env bash
# run_stability.sh — Launch WiFi 2-hour stability soak test
# Usage: bash run_stability.sh [--band 5G] [--duration 7200] [--interval 60]

set -euo pipefail
cd "$(dirname "$0")"

BAND=5G
DURATION=7200   # 2 hours
INTERVAL=60

# Parse optional args
while [[ $# -gt 0 ]]; do
    case $1 in
        --band)     BAND="$2";     shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --interval) INTERVAL="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

if [[ ! -f .venv/bin/activate ]]; then
    echo "[!] .venv not found. Run bootstrap_testpc.sh first."
    exit 1
fi
source .venv/bin/activate

echo "=============================================="
echo " WiFi Stability Soak Test"
echo " Band     : $BAND"
echo " Duration : ${DURATION}s ($(( DURATION / 60 )) minutes)"
echo " Interval : ${INTERVAL}s per check"
echo " Started  : $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="
echo

python3 stability_test.py \
    --band "$BAND" \
    --duration "$DURATION" \
    --interval "$INTERVAL"

STATUS=$?
echo
if [[ $STATUS -eq 0 ]]; then
    echo "[PASS] Stability test completed with no issues."
else
    echo "[FAIL] Stability test detected issues. Check stability_report.md in the run dir."
fi
exit $STATUS
