"""
tests/test_association.py
-------------------------
Functional test: BPI-R4 associates to DUT's WiFi on each band,
gets a DHCP lease, and pings the DUT over the RF link.
"""
from __future__ import annotations

import re
import time

import pytest


pytestmark = pytest.mark.rf

# Band → config keys + security mode
_BAND_CFG = {
    "2G": ("bpi_sta.wifi_iface_2g", "dut.wifi.ssid_2g", "wpa2_wpa3"),
    "5G": ("bpi_sta.wifi_iface_5g", "dut.wifi.ssid_5g", "wpa2_wpa3"),
    "6G": ("bpi_sta.wifi_iface_6g", "dut.wifi.ssid_6g", "wpa3"),
}


def _band_iface(cfg, band: str) -> str:
    iface_key, _, _ = _BAND_CFG[band]
    return cfg.get(iface_key)


def _write_wpa_conf(bpi_ssh, ssid: str, psk: str, security: str = "wpa2_wpa3") -> str:
    """Write wpa_supplicant config. security: 'wpa2_wpa3' or 'wpa3' (SAE-only)."""
    path = "/tmp/wpa_test.conf"
    if security == "wpa3":
        # SAE-only (6 GHz / WPA3-only AP)
        network_block = (
            "network={\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{psk}"\n'
            "    key_mgmt=SAE\n"
            "    proto=RSN\n"
            "    ieee80211w=2\n"
            "}\n"
        )
    else:
        # WPA2/WPA3 mixed
        network_block = (
            "network={\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{psk}"\n'
            "    key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE\n"
            "    proto=RSN\n"
            "    ieee80211w=1\n"
            "}\n"
        )
    global_opts = "ctrl_interface=/var/run/wpa_supplicant\n"
    if security == "wpa3":
        global_opts += "sae_pwe=2\n"  # 6 GHz AP requires H2E; wpa_supplicant default may not try it
    content = global_opts + network_block
    cmd = f"cat > {path} <<'EOF'\n{content}\nEOF"
    bpi_ssh.run(cmd, check=True)
    return path


def _restore_all_wifi_ifaces(bpi_ssh, cfg):
    """Kill wpa_supplicant and restore all band interfaces to br-lan."""
    bpi_ssh.run("killall wpa_supplicant 2>/dev/null; sleep 1; true")
    for key in ("bpi_sta.wifi_iface_2g", "bpi_sta.wifi_iface_5g", "bpi_sta.wifi_iface_6g"):
        iface = cfg.get(key)
        if not iface:
            continue
        bpi_ssh.run(f"rm -f /var/run/wpa_supplicant/{iface} 2>/dev/null; true")
        bpi_ssh.run(f"ip addr flush dev {iface} 2>/dev/null; true")
        bpi_ssh.run(f"ip link set {iface} down 2>/dev/null; true")
        bpi_ssh.run(f"brctl addif br-lan {iface} 2>/dev/null; true")
        bpi_ssh.run(f"ip link set {iface} up 2>/dev/null; true")


@pytest.mark.parametrize("band", ["2G", "5G", "6G"])
def test_bpi_associates_to_dut(cfg, dut_ssh, bpi_ssh, band):
    """BPI-R4 connects to DUT's SSID on each band, gets IP, and pings over RF."""
    iface_key, ssid_key, security = _BAND_CFG[band]
    iface = cfg.get(iface_key)
    ssid  = cfg.get(ssid_key)
    psk   = cfg.get("dut.wifi.psk")

    assert iface, f"Missing config: {iface_key}"
    assert ssid,  f"Missing config: {ssid_key}"

    # 1. Clean state: restore all ifaces to br-lan, then detach current one
    _restore_all_wifi_ifaces(bpi_ssh, cfg)
    bpi_ssh.run(f"ip link set {iface} down")
    bpi_ssh.run(f"brctl delif br-lan {iface} 2>/dev/null; true")
    bpi_ssh.run(f"ip addr flush dev {iface} 2>/dev/null; true")
    bpi_ssh.run(f"ip link set {iface} up")
    time.sleep(1)

    # 2. Write wpa_supplicant config and start
    conf = _write_wpa_conf(bpi_ssh, ssid, psk, security)
    bpi_ssh.run(f"wpa_supplicant -B -i {iface} -c {conf} -D nl80211", check=True)

    # 3. Wait up to 20s for association
    associated = False
    for _ in range(20):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
        if "Connected to" in out:
            associated = True
            print(f"\nAssociated on {band}: {out.strip().splitlines()[0]}")
            break
    assert associated, f"BPI did not associate to {ssid} on {band} within 20s"

    # 4. Request IP — wait up to 15s for route to appear
    bpi_ssh.run(f"udhcpc -i {iface} -t 10 -n 2>&1 || true")
    bpi_ip = None
    for _ in range(15):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"ip -4 addr show {iface}")
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            _, rout, _ = bpi_ssh.run(f"ip route show dev {iface}")
            if rout.strip():
                bpi_ip = m.group(1)
                break
    assert bpi_ip, f"No IPv4 + route on {iface} after DHCP"
    print(f"BPI got IP: {bpi_ip}")

    # 5. Confirm WiFi still up, then ping DUT over the RF link
    _, link, _ = bpi_ssh.run(f"iw dev {iface} link")
    assert "Connected to" in link, f"WiFi dropped before ping: {link.strip()}"
    _, out, _ = bpi_ssh.run(f"ping -I {iface} -c 5 -W 2 {cfg.get('dut.host')}")
    # Busybox ping: "N packets received" / standard ping: "N received"
    received = 0
    for line in out.splitlines():
        m = re.search(r"(\d+)\s+(?:packets\s+)?received", line)
        if m:
            received = int(m.group(1))
    assert received >= 4, f"Ping loss too high over RF ({band}): {received}/5\n{out}"
    print(f"Ping over RF ({band}): {received}/5 replies received")


def test_deassociation_cleanup(bpi_ssh, cfg):
    """Restore all band interfaces to br-lan after association tests."""
    _restore_all_wifi_ifaces(bpi_ssh, cfg)
    # Verify all ifaces are disconnected
    for key in ("bpi_sta.wifi_iface_2g", "bpi_sta.wifi_iface_5g", "bpi_sta.wifi_iface_6g"):
        iface = cfg.get(key)
        if not iface:
            continue
        _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
        assert "Not connected" in out or "not associated" in out.lower(), \
            f"{iface} still connected after cleanup"
