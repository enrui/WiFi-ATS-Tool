#!/usr/bin/env bash
# ==============================================================================
#  bootstrap_bpi.sh
#  ---------------------------------------------------------------------------
#  Configures Banana Pi BPI-R4 as a WiFi 7 STA (client) for testing.
#  Reads target IP from config.yaml and SSHes into the device to install tools.
#
#  Usage (from Test PC):
#    bash bootstrap_bpi.sh
#
#  Prerequisites:
#    - config.yaml filled in with bpi_sta host / credentials
#    - SSH key copied to BPI-R4 (or sshpass configured)
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="${PROJECT_ROOT}/config.yaml"

if [[ ! -f "$CONFIG" ]]; then
  error "config.yaml not found. Copy config.yaml.example and fill in values first."
  exit 1
fi

# ---------- Parse config.yaml (using python since yq may not be installed) ----------
BPI_HOST=$(python3 -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['bpi_sta']['host'])")
BPI_USER=$(python3 -c "import yaml; print(yaml.safe_load(open('$CONFIG'))['bpi_sta']['ssh_user'])")

info "Target BPI-R4: ${BPI_USER}@${BPI_HOST}"

# ---------- Check reachability ----------
if ! ping -c 1 -W 2 "$BPI_HOST" &>/dev/null; then
  error "Cannot ping $BPI_HOST. Check network wiring and IP settings."
  exit 1
fi

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${BPI_USER}@${BPI_HOST}" 'true' 2>/dev/null; then
  warn "SSH to ${BPI_USER}@${BPI_HOST} requires password or key setup."
  warn "Recommended:  ssh-copy-id ${BPI_USER}@${BPI_HOST}"
  read -rp "Continue with interactive password? [y/N] " yn
  [[ "$yn" =~ ^[Yy]$ ]] || exit 1
fi

# ---------- Detect OS on BPI ----------
info "Detecting OS on BPI-R4..."
OS_TYPE=$(ssh "${BPI_USER}@${BPI_HOST}" 'if [ -f /etc/openwrt_release ]; then echo openwrt; elif [ -f /etc/lsb-release ]; then echo ubuntu; else echo unknown; fi')
info "  Detected: ${OS_TYPE}"

# ---------- Install packages ----------
if [[ "$OS_TYPE" == "openwrt" ]]; then
  info "Installing packages via opkg..."
  ssh "${BPI_USER}@${BPI_HOST}" bash <<'EOF'
    set -e
    opkg update
    opkg install iperf3 wpa-supplicant-openssl iw hostapd-utils tcpdump-mini || true
EOF

elif [[ "$OS_TYPE" == "ubuntu" ]]; then
  info "Installing packages via apt..."
  ssh "${BPI_USER}@${BPI_HOST}" bash <<'EOF'
    set -e
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
      iperf3 wpasupplicant iw \
      wireless-tools net-tools \
      tcpdump ethtool
EOF

else
  warn "Unknown OS type. Please install: iperf3, wpa_supplicant, iw manually."
fi

# ---------- Verify wireless interface ----------
info "Checking wireless interfaces on BPI-R4..."
ssh "${BPI_USER}@${BPI_HOST}" 'iw dev 2>/dev/null | grep -E "Interface|type" || echo "(none)"'

# ---------- Deploy helper scripts to BPI ----------
info "Deploying helper scripts to BPI-R4:/root/..."
scp -q "${PROJECT_ROOT}/scripts/bpi_connect.sh" "${BPI_USER}@${BPI_HOST}:/root/" 2>/dev/null || true
scp -q "${PROJECT_ROOT}/scripts/bpi_iperf_server.sh" "${BPI_USER}@${BPI_HOST}:/root/" 2>/dev/null || true
ssh "${BPI_USER}@${BPI_HOST}" 'chmod +x /root/bpi_*.sh 2>/dev/null || true'

echo
info "BPI-R4 bootstrap complete."
echo
echo "Test with:"
echo "  ssh ${BPI_USER}@${BPI_HOST} 'iperf3 --version'"
echo "  ssh ${BPI_USER}@${BPI_HOST} 'iw dev'"
echo
