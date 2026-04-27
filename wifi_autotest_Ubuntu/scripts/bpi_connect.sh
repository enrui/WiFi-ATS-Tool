#!/bin/sh
# bpi_connect.sh — run on BPI-R4 to connect to a given SSID
# Usage:  bpi_connect.sh <ssid> <psk> [iface]

SSID="${1:?usage: $0 <ssid> <psk> [iface]}"
PSK="${2:?usage: $0 <ssid> <psk> [iface]}"
IFACE="${3:-wlan0}"

CONF=/tmp/wpa.conf
cat > "$CONF" <<EOF
ctrl_interface=/var/run/wpa_supplicant
network={
    ssid="$SSID"
    psk="$PSK"
    key_mgmt=WPA-PSK WPA-PSK-SHA256
    proto=RSN
}
EOF

killall wpa_supplicant 2>/dev/null
sleep 1
ip link set "$IFACE" down
ip link set "$IFACE" up
wpa_supplicant -B -i "$IFACE" -c "$CONF" -D nl80211

# Wait for association
for i in $(seq 1 15); do
    if iw dev "$IFACE" link | grep -q "Connected to"; then
        echo "Associated after ${i}s"
        udhcpc -i "$IFACE" -t 5 -n 2>/dev/null || dhclient -1 "$IFACE"
        exit 0
    fi
    sleep 1
done

echo "Failed to associate within 15s" >&2
exit 1
