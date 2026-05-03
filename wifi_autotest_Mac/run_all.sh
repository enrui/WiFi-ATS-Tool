#!/usr/bin/env bash
# ==============================================================================
#  run_all.sh
#  ---------------------------------------------------------------------------
#  End-to-end pipeline: run tests, collect logs, analyze with Claude, report.
#
#  Usage:
#    bash run_all.sh                   # run smoke tests only
#    bash run_all.sh rf                # include RF tests (association + throughput)
#    bash run_all.sh rf --skip-ai      # skip Claude Code analysis
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Load .env if present (ANTHROPIC_API_KEY etc.)
if [[ -f "$PROJECT_ROOT/.env" ]]; then
  set -a; source "$PROJECT_ROOT/.env"; set +a
fi

# Activate venv if present
if [[ -f "$PROJECT_ROOT/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  source "$PROJECT_ROOT/.venv/bin/activate"
fi

# Parse args
MARKERS=""
SKIP_AI=false
for arg in "$@"; do
  case "$arg" in
    rf)        MARKERS="-m rf" ;;
    --skip-ai) SKIP_AI=true ;;
    *)         echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

# Create run dir
STAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="runs/${STAMP}"
RUN_ABS="${PROJECT_ROOT}/${RUN_DIR}"
mkdir -p "$RUN_ABS"
echo -e "${GREEN}[+]${NC} Run dir: $RUN_DIR"

# ---------- 1. Pytest ----------
echo -e "${GREEN}[+]${NC} Running pytest..."
set +e
WIFI_AUTOTEST_CONFIG="${PROJECT_ROOT}/config.yaml" \
WIFI_AUTOTEST_RUN_DIR="${RUN_ABS}" \
pytest tests/ $MARKERS \
  --html="${RUN_ABS}/pytest_report.html" --self-contained-html \
  --junit-xml="${RUN_ABS}/junit.xml" \
  -v 2>&1 | tee "${RUN_ABS}/pytest_stdout.log"
PYTEST_RC=${PIPESTATUS[0]}
set -e

echo -e "${GREEN}[+]${NC} pytest exit code: $PYTEST_RC"

# ---------- 2. Collect device logs ----------
echo -e "${GREEN}[+]${NC} Collecting device logs..."
python tools/collect_logs.py --run "$RUN_ABS" || \
  echo -e "${YELLOW}[!]${NC} Log collection failed (non-fatal)"

# ---------- 3. Live diagnostics (always on failure) ----------
if [[ $PYTEST_RC -ne 0 ]]; then
  echo -e "${GREEN}[+]${NC} Failures detected — collecting live diagnostics..."
  python tools/analyze_logs.py "$RUN_ABS" || \
    echo -e "${YELLOW}[!]${NC} Diagnostics collection failed (non-fatal)"
else
  echo -e "${GREEN}[+]${NC} All tests passed — skipping diagnostics."
fi

# ---------- 4. Claude API analysis (on failure) ----------
if [[ $PYTEST_RC -ne 0 && "$SKIP_AI" == "false" ]]; then
  if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo -e "${YELLOW}[!]${NC} ANTHROPIC_API_KEY not set — skipping AI analysis."
    echo -e "${YELLOW}[!]${NC} Set it with: export ANTHROPIC_API_KEY='sk-ant-...'"
  else
    echo -e "${GREEN}[+]${NC} Running Claude API analysis..."
    python tools/claude_api_analyze.py "$RUN_ABS" || \
      echo -e "${YELLOW}[!]${NC} Claude API analysis failed (non-fatal)"
    [[ -f "${RUN_ABS}/claude_report.md" ]] && \
      echo -e "${GREEN}[+]${NC} AI analysis written to ${RUN_DIR}/claude_report.md"
  fi
fi

# ---------- 5. Summary report ----------
echo -e "${GREEN}[+]${NC} Generating summary report..."
python tools/generate_report.py "$RUN_ABS" || \
  echo -e "${YELLOW}[!]${NC} Summary report generation failed (non-fatal)"

# ---------- 6. Summary ----------
echo
echo "==========================================================="
echo " Summary"
echo "==========================================================="
echo "  Run dir:      $RUN_DIR"
echo "  pytest:       $([ $PYTEST_RC -eq 0 ] && echo PASS || echo FAIL)"
[[ -f "${RUN_ABS}/summary_report.html" ]] && \
  echo "  Report:       ${RUN_DIR}/summary_report.html"
[[ -f "${RUN_ABS}/claude_report.md" ]] && \
  echo "  AI report:    ${RUN_DIR}/claude_report.md"
echo "==========================================================="

exit $PYTEST_RC
