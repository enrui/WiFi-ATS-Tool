#!/usr/bin/env bash
# run_bg.sh — 背景執行測試，立刻回到 shell
#
# Usage:
#   bash run_bg.sh                    # pytest smoke only
#   bash run_bg.sh rf                 # pytest RF tests（最常用）
#   bash run_bg.sh rf --skip-ai       # pytest RF，跳過 AI 分析
#   bash run_bg.sh stability          # 2 小時穩定度 soak test
#   bash run_bg.sh stability --band 2G --duration 3600
#   bash run_bg.sh rf stability       # pytest RF，完成後接著跑 stability

set -euo pipefail
cd "$(dirname "$0")"

# Load .env if present (ANTHROPIC_API_KEY etc.)
if [[ -f ".env" ]]; then
  set -a; source ".env"; set +a
fi

# ---------- Parse arguments ----------
RUN_RF=false
RUN_STABILITY=false
RF_ARGS=()
STABILITY_ARGS=()
CURRENT=""

for arg in "$@"; do
  case "$arg" in
    rf)          RUN_RF=true;        CURRENT="rf" ;;
    stability)   RUN_STABILITY=true; CURRENT="stability" ;;
    *)
      if [[ "$CURRENT" == "stability" ]]; then
        STABILITY_ARGS+=("$arg")
      else
        RF_ARGS+=("$arg")
      fi
      ;;
  esac
done

# Default: smoke only (no rf, no stability)
if [[ "$RUN_RF" == "false" && "$RUN_STABILITY" == "false" ]]; then
  RUN_RF=true
  RF_ARGS=()
fi

# ---------- Build summary ----------
STAMP=$(date +%Y%m%d-%H%M%S)
BGLOG="runs/bg_${STAMP}.log"
mkdir -p runs

echo "=============================================="
echo " WiFi AutoTest — Background Run"
if [[ "$RUN_RF" == "true" ]]; then
  echo " [1] pytest RF tests  args: rf ${RF_ARGS[*]:-}"
fi
if [[ "$RUN_STABILITY" == "true" ]]; then
  echo " [2] Stability soak   args: ${STABILITY_ARGS[*]:-default (5G / 2h / 60s)}"
fi
echo " Log     : $BGLOG"
echo " Started : $(date '+%Y-%m-%d %H:%M:%S')"
echo "=============================================="

# ---------- Build background command ----------
# Run tasks sequentially inside a subshell so they share one log file
{
  if [[ "$RUN_RF" == "true" ]]; then
    echo ""
    echo "========================================"
    echo " [STEP] pytest RF tests"
    echo "========================================"
    bash run_all.sh rf ${RF_ARGS[@]+"${RF_ARGS[@]}"}
    RF_RC=$?
    echo ""
    echo "[run_bg] pytest exit code: $RF_RC"
  fi

  if [[ "$RUN_STABILITY" == "true" ]]; then
    echo ""
    echo "========================================"
    echo " [STEP] Stability soak test"
    echo "========================================"
    bash run_stability.sh ${STABILITY_ARGS[@]+"${STABILITY_ARGS[@]}"}
    ST_RC=$?
    echo ""
    echo "[run_bg] stability exit code: $ST_RC"
  fi

  echo ""
  echo "=============================================="
  echo " [run_bg] All tasks finished: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "=============================================="
} > "$BGLOG" 2>&1 &

PID=$!

echo ""
echo "  PID $PID started. Shell is free."
echo ""
echo "  Monitor  : tail -f $BGLOG"
echo "  Status   : kill -0 $PID 2>/dev/null && echo running || echo done"
echo "  Stop     : kill $PID"
echo "=============================================="
