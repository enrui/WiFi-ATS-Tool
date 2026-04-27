"""
tests/test_legacy_compat.py
---------------------------
Verify that the DUT accepts connections from clients simulating legacy WiFi modes.

BPI-R4 wpa_supplicant flags used (note: disable_he not supported on this build):
  802.11b/g  → disable_ht=1, WPA2-PSK only   (2.4G only)
  802.11n    → disable_vht=1, WPA2-PSK only   (2.4G / 5G)
  802.11ac   → WPA2-PSK only (no SAE)         (5G only)
  802.11ax   → no flags (default, WPA2+WPA3)  (2.4G / 5G / 6G)

Only association is verified — no throughput assertion.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import pytest

from tests.test_association import (
    _band_iface, _write_wpa_conf, _restore_all_wifi_ifaces, _BAND_CFG
)

pytestmark = pytest.mark.rf


# ---------------------------------------------------------------------------
# Legacy mode definitions
# ---------------------------------------------------------------------------
@dataclass
class LegacyMode:
    name: str
    disable_ht: bool = False
    disable_vht: bool = False
    wpa2_only: bool = False    # use WPA-PSK only (no SAE) to simulate pre-WPA3 device

    def extra_network_lines(self) -> str:
        lines = ""
        if self.disable_ht:
            lines += "    disable_ht=1\n"
        if self.disable_vht:
            lines += "    disable_vht=1\n"
        return lines


MODES_2G = [
    LegacyMode("802.11b/g", disable_ht=True,  wpa2_only=True),
    LegacyMode("802.11n",   disable_vht=True, wpa2_only=True),
    LegacyMode("802.11ax"),
]

MODES_5G = [
    LegacyMode("802.11a/n", disable_vht=True, wpa2_only=True),
    LegacyMode("802.11ac",  wpa2_only=True),
    LegacyMode("802.11ax"),
]

MODES_6G = [
    LegacyMode("802.11ax"),   # 6G is WPA3-only; no legacy mode possible
]


# ---------------------------------------------------------------------------
# Core helper: write wpa_supplicant config with legacy flags
# ---------------------------------------------------------------------------
def _write_wpa_conf_legacy(bpi_ssh, ssid: str, psk: str,
                            security: str, mode: LegacyMode) -> str:
    path = "/tmp/wpa_legacy.conf"
    if security == "wpa3" and not mode.wpa2_only:
        # 6G SAE-only AP, full AX mode
        network_block = (
            "network={\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{psk}"\n'
            "    key_mgmt=SAE\n"
            "    proto=RSN\n"
            "    ieee80211w=2\n"
            + mode.extra_network_lines() +
            "}\n"
        )
        global_opts = "ctrl_interface=/var/run/wpa_supplicant\nsae_pwe=2\n"
    elif mode.wpa2_only:
        # Simulate legacy device: WPA2-PSK only, no SAE, no MFP required
        network_block = (
            "network={\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{psk}"\n'
            "    key_mgmt=WPA-PSK\n"
            "    proto=RSN WPA\n"
            "    ieee80211w=0\n"
            + mode.extra_network_lines() +
            "}\n"
        )
        global_opts = "ctrl_interface=/var/run/wpa_supplicant\n"
    else:
        # Default: WPA2/WPA3 mixed
        network_block = (
            "network={\n"
            f'    ssid="{ssid}"\n'
            f'    psk="{psk}"\n'
            "    key_mgmt=WPA-PSK WPA-PSK-SHA256 SAE\n"
            "    proto=RSN\n"
            "    ieee80211w=1\n"
            + mode.extra_network_lines() +
            "}\n"
        )
        global_opts = "ctrl_interface=/var/run/wpa_supplicant\n"
    content = global_opts + network_block
    bpi_ssh.run(f"cat > {path} <<'EOF'\n{content}\nEOF", check=True)
    return path


# ---------------------------------------------------------------------------
# Core helper: associate BPI with a specific legacy mode and verify
# ---------------------------------------------------------------------------
def _associate_legacy(bpi_ssh, cfg, band: str, mode: LegacyMode):
    iface_key, ssid_key, security = _BAND_CFG[band]
    iface = cfg.get(iface_key)
    ssid  = cfg.get(ssid_key)
    psk   = cfg.get("dut.wifi.psk")

    assert iface and ssid, f"Missing config for band {band}"

    # Clean state
    _restore_all_wifi_ifaces(bpi_ssh, cfg)
    for key in ("bpi_sta.wifi_iface_2g", "bpi_sta.wifi_iface_5g", "bpi_sta.wifi_iface_6g"):
        other = cfg.get(key)
        if other and other != iface:
            bpi_ssh.run(f"ip link set {other} down 2>/dev/null; true")
    bpi_ssh.run(f"ip link set {iface} down")
    bpi_ssh.run(f"brctl delif br-lan {iface} 2>/dev/null; true")
    bpi_ssh.run(f"ip addr flush dev {iface} 2>/dev/null; true")
    bpi_ssh.run(f"ip link set {iface} up")
    time.sleep(2)

    # Start wpa_supplicant with legacy flags
    conf = _write_wpa_conf_legacy(bpi_ssh, ssid, psk, security, mode)
    bpi_ssh.run(f"wpa_supplicant -B -i {iface} -c {conf} -D nl80211", check=True)

    # Wait up to 25s for association
    associated = False
    for _ in range(25):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
        if "Connected to" in out:
            associated = True
            print(f"\n[{band} {mode.name}] Associated: {out.strip().splitlines()[0]}")
            break

    assert associated, (
        f"[{band}] BPI failed to associate in mode {mode.name} within 25s"
    )

    # Quick DHCP + ping to confirm link is usable
    bpi_ssh.run(f"udhcpc -i {iface} -t 8 -n 2>&1 || true")
    dut_ip = cfg.get("dut.host")
    _, ping_out, _ = bpi_ssh.run(f"ping -I {iface} -c 3 -W 2 {dut_ip}")
    received = 0
    for line in ping_out.splitlines():
        m = re.search(r"(\d+)\s+(?:packets\s+)?received", line)
        if m:
            received = int(m.group(1))
    assert received >= 2, (
        f"[{band} {mode.name}] Ping failed ({received}/3): {ping_out}"
    )
    print(f"[{band} {mode.name}] Ping OK ({received}/3)")


# ---------------------------------------------------------------------------
# 2.4G legacy compatibility tests
# ---------------------------------------------------------------------------
class TestLegacyCompat2G:

    @pytest.fixture(autouse=True, scope="class")
    def cleanup(self, bpi_ssh, cfg):
        yield
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_80211bg(self, bpi_ssh, cfg):
        """Simulate 802.11b/g client (no HT) on 2.4G."""
        _associate_legacy(bpi_ssh, cfg, "2G", MODES_2G[0])

    def test_80211n(self, bpi_ssh, cfg):
        """Simulate 802.11n client (HT only, no VHT/HE) on 2.4G."""
        _associate_legacy(bpi_ssh, cfg, "2G", MODES_2G[1])

    def test_80211ax(self, bpi_ssh, cfg):
        """802.11ax client (default, no restrictions) on 2.4G."""
        _associate_legacy(bpi_ssh, cfg, "2G", MODES_2G[2])


# ---------------------------------------------------------------------------
# 5G legacy compatibility tests
# ---------------------------------------------------------------------------
class TestLegacyCompat5G:

    @pytest.fixture(autouse=True, scope="class")
    def cleanup(self, bpi_ssh, cfg):
        yield
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_80211an(self, bpi_ssh, cfg):
        """Simulate 802.11a/n client (no VHT/HE) on 5G."""
        _associate_legacy(bpi_ssh, cfg, "5G", MODES_5G[0])

    def test_80211ac(self, bpi_ssh, cfg):
        """Simulate 802.11ac client (no HE) on 5G."""
        _associate_legacy(bpi_ssh, cfg, "5G", MODES_5G[1])

    def test_80211ax(self, bpi_ssh, cfg):
        """802.11ax client (default) on 5G."""
        _associate_legacy(bpi_ssh, cfg, "5G", MODES_5G[2])


# ---------------------------------------------------------------------------
# 6G legacy compatibility tests (AX only — 6G does not support b/g/n/ac)
# ---------------------------------------------------------------------------
class TestLegacyCompat6G:

    @pytest.fixture(autouse=True, scope="class")
    def cleanup(self, bpi_ssh, cfg):
        yield
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_80211ax(self, bpi_ssh, cfg):
        """802.11ax client on 6G (only supported mode)."""
        _associate_legacy(bpi_ssh, cfg, "6G", MODES_6G[0])
