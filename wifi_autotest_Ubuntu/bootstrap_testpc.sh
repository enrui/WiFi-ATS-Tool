#!/usr/bin/env bash
# ==============================================================================
#  bootstrap_testpc.sh
#  ---------------------------------------------------------------------------
#  Installs all required software on the Test PC (Ubuntu 22.04 LTS).
#  Idempotent — safe to run multiple times.
#
#  Usage:
#    bash bootstrap_testpc.sh
#
#  Prerequisites:
#    - Ubuntu 22.04 LTS (or 24.04)
#    - sudo privileges
#    - Internet access
# ==============================================================================

set -euo pipefail

# ---------- Pretty output ----------
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }

# ---------- Pre-flight ----------
if [[ $EUID -eq 0 ]]; then
  error "Do not run this script as root. It will sudo when needed."
  exit 1
fi

if ! command -v lsb_release &>/dev/null || [[ "$(lsb_release -is)" != "Ubuntu" ]]; then
  warn "This script targets Ubuntu. Other distros may need manual tweaks."
fi

info "Starting Test PC bootstrap..."

# ---------- APT packages ----------
info "Updating apt cache..."
sudo apt-get update -qq

info "Installing system packages..."
sudo apt-get install -y -qq \
  python3 python3-pip python3-venv \
  git curl wget jq \
  iperf3 \
  minicom picocom \
  openssh-client sshpass \
  net-tools iputils-ping \
  build-essential \
  tftp-hpa tftpd-hpa \
  usbutils

# ---------- User groups for serial access ----------
if ! groups "$USER" | grep -q dialout; then
  info "Adding $USER to 'dialout' group (required for /dev/ttyUSB*)..."
  sudo usermod -aG dialout "$USER"
  warn "You must log out and back in for group change to take effect."
fi

# ---------- Python venv ----------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
  info "Creating Python virtual environment at ${VENV_DIR}..."
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

info "Installing Python packages..."
pip install --quiet --upgrade pip
pip install --quiet \
  pytest \
  pytest-html \
  pytest-timeout \
  paramiko \
  pexpect \
  pyserial \
  pyyaml \
  anthropic \
  rich \
  tabulate

# ---------- Claude Code CLI (optional but recommended) ----------
if ! command -v claude &>/dev/null; then
  info "Installing Claude Code CLI via npm..."
  if ! command -v npm &>/dev/null; then
    info "npm not found, installing Node.js 20 LTS..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt-get install -y -qq nodejs
  fi
  sudo npm install -g @anthropic-ai/claude-code
else
  info "Claude Code CLI already installed ($(claude --version 2>/dev/null || echo 'unknown version'))."
fi

# ---------- Anthropic API key check ----------
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  warn "ANTHROPIC_API_KEY not set in environment."
  warn "Add to ~/.bashrc:   export ANTHROPIC_API_KEY='sk-ant-...'"
  warn "Without it, analyze_logs.py will not run."
fi

# ---------- Config file bootstrap ----------
if [[ ! -f "${PROJECT_ROOT}/config.yaml" ]]; then
  if [[ -f "${PROJECT_ROOT}/config.yaml.example" ]]; then
    cp "${PROJECT_ROOT}/config.yaml.example" "${PROJECT_ROOT}/config.yaml"
    warn "Created config.yaml from example. Edit it before running tests."
  fi
fi

# ---------- Verify ----------
info "Verifying installation..."
python3 -c "import pytest, paramiko, pexpect, serial, yaml, anthropic" \
  && info "  ✓ Python modules OK"
command -v iperf3 &>/dev/null && info "  ✓ iperf3 installed ($(iperf3 --version | head -1))"
ls /dev/ttyUSB* 2>/dev/null && info "  ✓ USB-serial device detected" || \
  warn "  - No /dev/ttyUSB* found yet (plug in USB-Serial adapter now)"

echo
info "Bootstrap complete."
echo
echo "Next steps:"
echo "  1. Edit  config.yaml  with your DUT / BPI-R4 IPs and credentials"
echo "  2. Run   source .venv/bin/activate"
echo "  3. Run   bash bootstrap_bpi.sh    (to configure BPI-R4)"
echo "  4. Run   pytest tests/test_smoke.py -v"
echo
