#!/usr/bin/env bash
# ==============================================================================
#  bootstrap_testpc.sh
#  ---------------------------------------------------------------------------
#  Installs all required software on the Test PC.
#  Auto-detects macOS or Ubuntu/Debian and uses the right package manager.
#  Idempotent — safe to run multiple times.
#
#  Usage:
#    bash bootstrap_testpc.sh
#
#  Prerequisites:
#    macOS:  Xcode Command Line Tools (will prompt if missing)
#    Linux:  Ubuntu 22.04+ or Debian 12+, sudo privileges
#    Both:   Internet access
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }
step()  { echo -e "${BLUE}==>${NC} $*"; }

# ---------- OS detection ----------
detect_os() {
  case "$(uname -s)" in
    Darwin)  echo "macos" ;;
    Linux)
      if [[ -f /etc/os-release ]] && grep -qiE "ubuntu|debian" /etc/os-release; then
        echo "linux"
      else
        echo "linux-other"
      fi ;;
    *) echo "unknown" ;;
  esac
}

OS=$(detect_os)
info "Detected OS: $OS"

case "$OS" in
  macos|linux) ;;
  linux-other) warn "Non-Ubuntu/Debian Linux. Manual package install may be needed." ;;
  *) error "Unsupported OS. This script supports macOS and Ubuntu/Debian."; exit 1 ;;
esac

if [[ "$OS" == "linux" && $EUID -eq 0 ]]; then
  error "Do not run as root on Linux. The script will sudo when needed."
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ==============================================================================
# macOS branch
# ==============================================================================
install_macos() {
  step "macOS installation path"

  # Xcode CLT
  if ! xcode-select -p &>/dev/null; then
    info "Xcode Command Line Tools not found, prompting install..."
    xcode-select --install || true
    warn "Re-run this script AFTER the Xcode CLT install dialog completes."
    exit 1
  fi

  # Homebrew
  if ! command -v brew &>/dev/null; then
    info "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    if [[ -d /opt/homebrew/bin ]]; then
      eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -d /usr/local/bin ]]; then
      eval "$(/usr/local/bin/brew shellenv)"
    fi
  else
    info "Homebrew present ($(brew --version | head -1))"
  fi

  info "Installing brew packages..."
  BREW_PKGS=(python@3.12 git curl wget jq iperf3 minicom picocom coreutils node)
  for pkg in "${BREW_PKGS[@]}"; do
    if brew list --formula "$pkg" &>/dev/null; then
      info "  ✓ $pkg already installed"
    else
      info "  Installing $pkg..."
      brew install "$pkg" >/dev/null
    fi
  done

  # USB-serial device check
  info "Checking for USB-serial devices..."
  SERIAL_FOUND=0
  for dev in /dev/tty.usbserial-* /dev/tty.usbmodem* /dev/tty.SLAB_USBtoUART /dev/tty.wchusbserial*; do
    if [[ -e "$dev" ]]; then
      info "  Found: $dev"
      SERIAL_FOUND=1
    fi
  done
  if [[ $SERIAL_FOUND -eq 0 ]]; then
    warn "  No USB-serial device detected yet."
    warn "    FTDI FT232:  built-in to macOS 14+, just plug in"
    warn "    CP2102:      https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers"
    warn "    CH340/341:   https://github.com/WCHSoftGroup/ch34xser_macos"
  fi
}

# ==============================================================================
# Linux (Ubuntu/Debian) branch
# ==============================================================================
install_linux() {
  step "Linux (Ubuntu/Debian) installation path"

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
    usbutils

  if ! groups "$USER" | grep -q dialout; then
    info "Adding $USER to 'dialout' group (for /dev/ttyUSB*)..."
    sudo usermod -aG dialout "$USER"
    warn "You must log out and back in for group change to take effect."
  fi
}

# ==============================================================================
# Common: Python venv + Claude Code CLI
# ==============================================================================
install_python_env() {
  step "Setting up Python virtual environment"

  VENV_DIR="${PROJECT_ROOT}/.venv"

  if [[ "$OS" == "macos" ]]; then
    PY="$(brew --prefix python@3.12 2>/dev/null)/bin/python3.12"
    [[ -x "$PY" ]] || PY=python3
  else
    PY=python3
  fi

  if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating venv at ${VENV_DIR} using $PY"
    "$PY" -m venv "$VENV_DIR"
  fi

  # shellcheck disable=SC1091
  source "${VENV_DIR}/bin/activate"

  info "Installing Python packages..."
  pip install --quiet --upgrade pip
  pip install --quiet \
    pytest pytest-html pytest-timeout \
    paramiko pexpect pyserial pyyaml \
    anthropic rich tabulate
}

install_claude_cli() {
  step "Installing Claude Code CLI"

  if command -v claude &>/dev/null; then
    info "Claude Code already installed"
    return
  fi

  if ! command -v npm &>/dev/null; then
    if [[ "$OS" == "linux" ]]; then
      info "Installing Node.js 20 LTS via NodeSource..."
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
      sudo apt-get install -y -qq nodejs
    else
      error "npm not found (brew install node should have handled this)."
      return 1
    fi
  fi

  info "Installing @anthropic-ai/claude-code globally via npm..."
  if [[ "$OS" == "macos" ]]; then
    npm install -g @anthropic-ai/claude-code
  else
    sudo npm install -g @anthropic-ai/claude-code
  fi
}

# ==============================================================================
# Run installs
# ==============================================================================
case "$OS" in
  macos)             install_macos ;;
  linux|linux-other) install_linux ;;
esac

install_python_env
install_claude_cli

# ---------- API key check ----------
if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
  warn "ANTHROPIC_API_KEY not set in environment."
  if [[ "$OS" == "macos" ]]; then
    SHELL_RC="$HOME/.zshrc"
  else
    SHELL_RC="$HOME/.bashrc"
  fi
  warn "Add to $SHELL_RC:    export ANTHROPIC_API_KEY='sk-ant-...'"
fi

# ---------- Config bootstrap ----------
if [[ ! -f "${PROJECT_ROOT}/config.yaml" ]] && [[ -f "${PROJECT_ROOT}/config/config.yaml.example" ]]; then
  cp "${PROJECT_ROOT}/config/config.yaml.example" "${PROJECT_ROOT}/config.yaml"
  warn "Created config.yaml from example. Edit it before running tests."
fi

# ---------- Verify ----------
step "Verifying installation"
python3 -c "import pytest, paramiko, pexpect, serial, yaml, anthropic" 2>/dev/null \
  && info "  ✓ Python modules OK" \
  || warn "  ✗ Some Python modules missing"
command -v iperf3 &>/dev/null && info "  ✓ iperf3 ($(iperf3 --version 2>/dev/null | head -1))" \
  || warn "  ✗ iperf3 missing"
command -v claude &>/dev/null && info "  ✓ Claude Code CLI" || warn "  ✗ Claude Code CLI missing"

if [[ "$OS" == "macos" ]]; then
  SERIAL_DEVS=$(ls /dev/tty.usbserial-* /dev/tty.usbmodem* /dev/tty.SLAB_USBtoUART /dev/tty.wchusbserial* 2>/dev/null || true)
else
  SERIAL_DEVS=$(ls /dev/ttyUSB* 2>/dev/null || true)
fi

if [[ -n "$SERIAL_DEVS" ]]; then
  info "  ✓ USB-serial device(s) detected:"
  echo "$SERIAL_DEVS" | sed 's/^/      /'
else
  warn "  - No USB-serial device yet (plug in to verify)"
fi

echo
info "Bootstrap complete."
echo
echo "Next steps:"
echo "  1. Edit  config.yaml  with DUT / BPI-R4 IPs and credentials"
if [[ "$OS" == "macos" ]]; then
  echo "     For serial_port, use one of the paths shown above"
  echo "     (e.g. /dev/tty.usbserial-XXXX, NOT /dev/ttyUSB0)"
fi
echo "  2. Run   source .venv/bin/activate"
echo "  3. Run   bash bootstrap_bpi.sh"
echo "  4. Run   bash run_all.sh"
echo
