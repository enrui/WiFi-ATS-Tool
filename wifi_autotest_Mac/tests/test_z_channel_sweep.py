"""
tests/test_channel_sweep.py
---------------------------
Sweep across channels for each band: change DUT channel via UCI, reconnect BPI,
run TCP DL throughput, and confirm no channel significantly underperforms.

EJ has explicitly authorized DUT channel changes for this test suite only.
DUT channel/htmode is restored to original values at the end of each band class.

Channels tested:
  2.4G: 1, 6, 11          (HT20, non-overlapping standard channels)
  5G:   36, 40, 44, 48    (EHT80, UNII-1 non-DFS — avoids BPI DFS silence mode)
  6G:   1, 5, 9, 13, 17   (EHT80, PSC subset — EHT80 used for channel flexibility)

Pass criteria:
  - Association succeeds on every channel
  - TCP DL throughput ≥ per-band minimum on every channel
  - No channel is more than 2× worse than the best channel in the same sweep
"""
from __future__ import annotations

import json
import re
import time

import pytest

from tests.test_association import (
    _write_wpa_conf, _restore_all_wifi_ifaces, _BAND_CFG
)

pytestmark = pytest.mark.rf


# ---------------------------------------------------------------------------
# Channel sweep configuration
# ---------------------------------------------------------------------------
SWEEP_CFG = {
    "2G": {
        "radio":           "wifi0",
        "channels":        [1, 6, 11],
        "htmode":          "HT20",
        "restore_channel": "auto",
        "restore_htmode":  "EHT40",
        "throughput_min":  20,   # Mbps TCP DL — lower due to HT20
    },
    "5G": {
        "radio":           "wifi1",
        "channels":        [36, 40, 44, 48],
        "htmode":          "EHT80",
        "restore_channel": "36",
        "restore_htmode":  "EHT80",
        "throughput_min":  100,  # Mbps TCP DL
    },
    "6G": {
        "radio":           "wifi2",
        "channels":        [1, 5, 9, 13, 17],
        "htmode":          "EHT80",   # EHT80 for flexible channel selection
        "restore_channel": "auto",
        "restore_htmode":  "EHT320",
        "throughput_min":  150,  # Mbps TCP DL
    },
}

IPERF_DURATION = 8   # seconds per throughput sample
WIFI_RESTART_WAIT = 14  # seconds after `wifi` for hostapd to settle


# ---------------------------------------------------------------------------
# DUT channel control
# ---------------------------------------------------------------------------
def _set_dut_channel(dut_ssh, radio: str, channel: int | str, htmode: str):
    dut_ssh.run(f"uci set wireless.{radio}.channel={channel}")
    dut_ssh.run(f"uci set wireless.{radio}.htmode={htmode}")
    dut_ssh.run("uci commit wireless")
    dut_ssh.run("wifi", timeout=10)
    time.sleep(WIFI_RESTART_WAIT)
    print(f"\n[DUT] Channel set to {channel} ({htmode}), waited {WIFI_RESTART_WAIT}s")


def _restore_dut_channel(dut_ssh, band: str):
    cfg = SWEEP_CFG[band]
    _set_dut_channel(dut_ssh, cfg["radio"],
                     cfg["restore_channel"], cfg["restore_htmode"])
    print(f"[DUT] {band} channel restored to {cfg['restore_channel']} / {cfg['restore_htmode']}")


# ---------------------------------------------------------------------------
# BPI connect + throughput helper
# ---------------------------------------------------------------------------
def _ensure_iperf_server(dut_ssh):
    _, out, _ = dut_ssh.run("netstat -ln 2>/dev/null | grep :5201 || ss -ln 2>/dev/null | grep :5201")
    if ":5201" not in out:
        dut_ssh.run("killall iperf3 2>/dev/null; sleep 0.3; true")
        dut_ssh.run("iperf3 -s -D >/tmp/iperf3.log 2>&1")
        time.sleep(1)


def _connect_and_measure(bpi_ssh, dut_ssh, cfg, band: str) -> float:
    """Connect BPI to DUT on given band, run TCP DL iperf3, return Mbps."""
    scfg = SWEEP_CFG[band]
    iface_key, ssid_key, security = _BAND_CFG[band]
    iface = cfg.get(iface_key)
    ssid  = cfg.get(ssid_key)
    psk   = cfg.get("dut.wifi.psk")

    # Bring down other ifaces to avoid scan EBUSY
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

    conf = _write_wpa_conf(bpi_ssh, ssid, psk, security)
    bpi_ssh.run(f"wpa_supplicant -B -i {iface} -c {conf} -D nl80211", check=True)

    # Wait for association (up to 30s — channel scan may take extra time)
    associated = False
    for _ in range(30):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
        if "Connected to" in out:
            associated = True
            break
    assert associated, f"[{band}] BPI did not associate within 30s after channel change"

    # DHCP
    bpi_ssh.run(f"udhcpc -i {iface} -t 8 -n 2>&1 || true")
    dut_ip = cfg.get("dut.host")

    # iperf3 TCP DL
    _ensure_iperf_server(dut_ssh)
    json_out = f"/tmp/iperf_{band.lower()}_sweep.json"
    _, iperf_out, _ = bpi_ssh.run(
        f"iperf3 -c {dut_ip} -t {IPERF_DURATION} -J 2>/dev/null",
        timeout=IPERF_DURATION + 15
    )
    try:
        data = json.loads(iperf_out)
        s = data["end"].get("sum_received", data["end"].get("sum", {}))
        mbps = s["bits_per_second"] / 1e6
    except Exception:
        mbps = 0.0

    return mbps


# ---------------------------------------------------------------------------
# Base class for channel sweep bands
# ---------------------------------------------------------------------------
class _ChannelSweepBase:
    _band: str
    _results: dict[int, float] = {}

    @classmethod
    def _run_channel(cls, channel: int, bpi_ssh, dut_ssh, cfg):
        scfg = SWEEP_CFG[cls._band]
        _set_dut_channel(dut_ssh, scfg["radio"], channel, scfg["htmode"])
        mbps = _connect_and_measure(bpi_ssh, dut_ssh, cfg, cls._band)
        cls._results[channel] = mbps
        min_mbps = scfg["throughput_min"]
        print(f"\n[{cls._band} ch{channel}] TCP DL: {mbps:.1f} Mbps (min: {min_mbps})")
        assert mbps >= min_mbps, (
            f"[{cls._band} ch{channel}] Throughput below minimum: {mbps:.1f} < {min_mbps} Mbps"
        )

    @classmethod
    def _check_consistency(cls):
        if len(cls._results) < 2:
            return
        best  = max(cls._results.values())
        worst = min(cls._results.values())
        ratio = best / worst if worst > 0 else float("inf")
        print(f"\n[{cls._band}] Channel sweep results:")
        for ch, mbps in sorted(cls._results.items()):
            print(f"  ch{ch:3d}: {mbps:.1f} Mbps")
        print(f"  Best: {best:.1f}  Worst: {worst:.1f}  Ratio: {ratio:.2f}x")
        assert ratio < 2.0, (
            f"[{cls._band}] Channel inconsistency too large: "
            f"best={best:.1f} worst={worst:.1f} ratio={ratio:.2f}x"
        )


# ---------------------------------------------------------------------------
# 2.4G channel sweep
# ---------------------------------------------------------------------------
class TestChannelSweep2G(_ChannelSweepBase):
    _band = "2G"
    _results: dict[int, float] = {}

    @pytest.fixture(autouse=True, scope="class")
    def restore_channel(self, dut_ssh, bpi_ssh, cfg):
        self.__class__._results = {}
        yield
        _restore_dut_channel(dut_ssh, "2G")
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_ch1(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(1, bpi_ssh, dut_ssh, cfg)

    def test_ch6(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(6, bpi_ssh, dut_ssh, cfg)

    def test_ch11(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(11, bpi_ssh, dut_ssh, cfg)

    def test_consistency(self):
        """Verify no channel is more than 2× worse than the best."""
        self._check_consistency()


# ---------------------------------------------------------------------------
# 5G channel sweep (UNII-1 non-DFS only)
# ---------------------------------------------------------------------------
class TestChannelSweep5G(_ChannelSweepBase):
    _band = "5G"
    _results: dict[int, float] = {}

    @pytest.fixture(autouse=True, scope="class")
    def restore_channel(self, dut_ssh, bpi_ssh, cfg):
        self.__class__._results = {}
        yield
        _restore_dut_channel(dut_ssh, "5G")
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_ch36(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(36, bpi_ssh, dut_ssh, cfg)

    def test_ch40(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(40, bpi_ssh, dut_ssh, cfg)

    def test_ch44(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(44, bpi_ssh, dut_ssh, cfg)

    def test_ch48(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(48, bpi_ssh, dut_ssh, cfg)

    def test_consistency(self):
        """Verify no channel is more than 2× worse than the best."""
        self._check_consistency()


# ---------------------------------------------------------------------------
# 6G channel sweep (PSC channels, EHT80)
# ---------------------------------------------------------------------------
class TestChannelSweep6G(_ChannelSweepBase):
    _band = "6G"
    _results: dict[int, float] = {}

    @pytest.fixture(autouse=True, scope="class")
    def restore_channel(self, dut_ssh, bpi_ssh, cfg):
        self.__class__._results = {}
        yield
        _restore_dut_channel(dut_ssh, "6G")
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_ch1(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(1, bpi_ssh, dut_ssh, cfg)

    def test_ch5(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(5, bpi_ssh, dut_ssh, cfg)

    def test_ch9(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(9, bpi_ssh, dut_ssh, cfg)

    def test_ch13(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(13, bpi_ssh, dut_ssh, cfg)

    def test_ch17(self, bpi_ssh, dut_ssh, cfg):
        self._run_channel(17, bpi_ssh, dut_ssh, cfg)

    def test_consistency(self):
        """Verify no channel is more than 2× worse than the best."""
        self._check_consistency()
