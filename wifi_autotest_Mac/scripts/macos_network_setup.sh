#!/usr/bin/env bash
# ==============================================================================
#  scripts/macos_network_setup.sh
#  ---------------------------------------------------------------------------
#  Helper for macOS users to set a static IP on the Ethernet interface that
#  connects to the testbed switch. Only needed once during setup.
#
#  macOS uses `networksetup` instead of /etc/network/interfaces or netplan.
#
#  Usage:
#    bash scripts/macos_network_setup.sh
#    bash scripts/macos_network_setup.sh --revert    # back to DHCP
# ==============================================================================

set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[+]${NC} $*"; }
warn()  { echo -e "${YELLOW}[!]${NC} $*"; }
error() { echo -e "${RED}[✗]${NC} $*" >&2; }

if [[ "$(uname -s)" != "Darwin" ]]; then
  error "This script is for macOS only."
  exit 1
fi

# Default testbed network (matches SETUP.md)
DEFAULT_IP="192.168.99.10"
DEFAULT_MASK="255.255.255.0"
DEFAULT_GW=""   # no gateway needed for isolated mgmt LAN

REVERT=0
if [[ "${1:-}" == "--revert" ]]; then
  REVERT=1
fi

# ---------- Pick the network service ----------
info "Available network services:"
networksetup -listallnetworkservices | grep -v "asterisk denotes" | nl

echo
read -rp "Enter the number of the service to configure (e.g. Ethernet, USB 10/100/1000 LAN): " choice

SERVICE=$(networksetup -listallnetworkservices | grep -v "asterisk denotes" | sed -n "${choice}p")

if [[ -z "$SERVICE" ]]; then
  error "Invalid selection"
  exit 1
fi

info "Selected service: $SERVICE"

# ---------- Apply or revert ----------
if [[ $REVERT -eq 1 ]]; then
  info "Reverting '$SERVICE' to DHCP..."
  sudo networksetup -setdhcp "$SERVICE"
  info "Done. Run 'ifconfig' to confirm."
  exit 0
fi

read -rp "Static IP for Test PC [$DEFAULT_IP]: " IP
IP=${IP:-$DEFAULT_IP}

read -rp "Subnet mask [$DEFAULT_MASK]: " MASK
MASK=${MASK:-$DEFAULT_MASK}

read -rp "Gateway (leave empty for none) [$DEFAULT_GW]: " GW
GW=${GW:-$DEFAULT_GW}

info "Applying static IP to '$SERVICE'..."
if [[ -z "$GW" ]]; then
  sudo networksetup -setmanual "$SERVICE" "$IP" "$MASK" "0.0.0.0"
else
  sudo networksetup -setmanual "$SERVICE" "$IP" "$MASK" "$GW"
fi

info "Configuration applied. Verifying..."
sleep 1
networksetup -getinfo "$SERVICE"

echo
info "Done. Test connectivity:"
echo "  ping -c 3 192.168.99.1     # DUT"
echo "  ping -c 3 192.168.99.100   # BPI-R4"
echo
info "To revert later:  bash scripts/macos_network_setup.sh --revert"
