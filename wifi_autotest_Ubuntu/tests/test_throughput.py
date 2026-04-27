"""
tests/test_throughput.py
------------------------
Measure TCP/UDP throughput between BPI-R4 (STA) and DUT using iperf3.
Each band class associates via WiFi first so traffic flows over the RF link.

Topology:
  BPI (iperf3 client, WiFi STA)  --RF-->  DUT (AP + iperf3 server)
"""
from __future__ import annotations

import json
import re
import time

import pytest

from tests.test_association import _band_iface, _write_wpa_conf, _restore_all_wifi_ifaces


pytestmark = pytest.mark.rf

# Minimum acceptable throughput per band/direction (Mbps).
# Values calibrated for this specific testbed (BPI-R4 MT7996 in 4addr/WDS mode):
#   2G: 20 MHz ch1      5G: 80 MHz ch36 (EHT80, non-DFS)      6G: 320 MHz ch1
THROUGHPUT_MIN = {
    "2G_TCP_DL": 30,
    "2G_TCP_UL": 30,
    "2G_UDP_DL": 30,
    "5G_TCP_DL": 120,
    "5G_TCP_UL": 120,
    "5G_UDP_DL": 100,
    "6G_TCP_DL": 300,
    "6G_TCP_UL": 300,
    "6G_UDP_DL": 200,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wifi_connect(bpi_ssh, cfg, band: str) -> str:
    """Associate BPI to DUT WiFi on given band, return WiFi IP."""
    from tests.test_association import _BAND_CFG
    iface_key, ssid_key, security = _BAND_CFG[band]
    iface = cfg.get(iface_key)
    ssid  = cfg.get(ssid_key)
    psk   = cfg.get("dut.wifi.psk")

    _restore_all_wifi_ifaces(bpi_ssh, cfg)
    # Bring down all other WiFi interfaces so the MediaTek driver does not run
    # concurrent scans and return EBUSY (-16) on the target band's scan.
    for key in ("bpi_sta.wifi_iface_2g", "bpi_sta.wifi_iface_5g", "bpi_sta.wifi_iface_6g"):
        other = cfg.get(key)
        if other and other != iface:
            bpi_ssh.run(f"ip link set {other} down 2>/dev/null; true")
    bpi_ssh.run(f"ip link set {iface} down")
    bpi_ssh.run(f"brctl delif br-lan {iface} 2>/dev/null; true")
    bpi_ssh.run(f"ip addr flush dev {iface} 2>/dev/null; true")
    bpi_ssh.run(f"ip link set {iface} up")
    time.sleep(2)  # let driver settle after band switch

    conf = _write_wpa_conf(bpi_ssh, ssid, psk, security)
    bpi_ssh.run(f"wpa_supplicant -B -i {iface} -c {conf} -D nl80211", check=True)

    associated = False
    for _ in range(30):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
        if "Connected to" in out:
            associated = True
            break
    assert associated, f"[{band}] BPI failed to associate within 30s"

    bpi_ssh.run(f"udhcpc -i {iface} -t 10 -n 2>&1 || true")
    wifi_ip = None
    for _ in range(15):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"ip -4 addr show {iface}")
        m = re.search(r"inet (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            _, rout, _ = bpi_ssh.run(f"ip route show dev {iface}")
            if rout.strip():
                wifi_ip = m.group(1)
                break
    assert wifi_ip, f"[{band}] No WiFi IP after DHCP"
    return wifi_ip


def _parse_iperf_json(output: str) -> dict:
    try:
        data = json.loads(output)
        end = data.get("end", {})
        sum_sent = end.get("sum_sent", end.get("sum", {}))
        bps = sum_sent.get("bits_per_second", 0)
        return {"mbps": bps / 1e6, "retransmits": sum_sent.get("retransmits", 0), "raw": data}
    except json.JSONDecodeError:
        for line in output.splitlines():
            m = re.search(r"([\d.]+)\s+Mbits/sec", line)
            if m and "sender" in line:
                return {"mbps": float(m.group(1)), "retransmits": 0, "raw": {}}
        raise RuntimeError(f"Could not parse iperf3 output: {output[:500]}")


def _run_iperf(bpi_ssh, dut_ip: str, wifi_ip: str,
               direction: str = "DL", proto: str = "TCP", duration: int = 10) -> dict:
    """Run iperf3 bound to the WiFi interface IP so traffic flows over RF."""
    flags = f"-J -B {wifi_ip}"
    if direction == "DL":
        flags += " -R"
    if proto == "UDP":
        flags += " -u -b 1G"
    cmd = f"iperf3 -c {dut_ip} -t {duration} {flags}"
    rc, out, err = bpi_ssh.run(cmd, timeout=duration + 15)
    assert rc == 0, f"iperf3 failed ({rc}):\n{err}"
    return _parse_iperf_json(out)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _restart_iperf_server(dut_ssh) -> None:
    """Kill and restart iperf3 -s on DUT, wait until port 5201 is ready."""
    dut_ssh.run("killall iperf3 2>/dev/null; sleep 0.3; true")
    dut_ssh.run("iperf3 -s -D >/tmp/iperf3.log 2>&1")
    time.sleep(1)
    _, out, _ = dut_ssh.run("netstat -ln 2>/dev/null | grep :5201 || ss -ln | grep :5201")
    assert ":5201" in out, "iperf3 server did not start on DUT"


def _ensure_iperf_server(dut_ssh) -> None:
    """Restart iperf3 server if it is no longer listening on port 5201."""
    _, out, _ = dut_ssh.run("netstat -ln 2>/dev/null | grep :5201 || ss -ln | grep :5201")
    if ":5201" not in out:
        import logging
        logging.getLogger(__name__).warning("iperf3 server not listening, restarting…")
        _restart_iperf_server(dut_ssh)


@pytest.fixture(scope="module")
def iperf_server_on_dut(dut_ssh):
    """Start iperf3 -s on DUT for the whole module, tear down after."""
    _restart_iperf_server(dut_ssh)
    yield
    dut_ssh.run("killall iperf3 2>/dev/null")


# ---------------------------------------------------------------------------
# Test classes — one per band
# ---------------------------------------------------------------------------

@pytest.mark.usefixtures("iperf_server_on_dut")
class TestThroughput2G:
    """2.4 GHz throughput over WiFi RF link."""

    @pytest.fixture(autouse=True, scope="class")
    def wifi_2g(self, bpi_ssh, cfg, dut_ssh):
        _ensure_iperf_server(dut_ssh)
        wifi_ip = _wifi_connect(bpi_ssh, cfg, "2G")
        self.__class__._wifi_ip = wifi_ip
        yield
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_tcp_downlink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "DL", "TCP", 10)
        (run_dir / "iperf_2g_tcp_dl.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["2G_TCP_DL"]
        print(f"\n2G TCP DL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps, \
            f"2G TCP DL below minimum: {result['mbps']:.1f} < {min_mbps} Mbps"

    def test_tcp_uplink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "UL", "TCP", 10)
        (run_dir / "iperf_2g_tcp_ul.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["2G_TCP_UL"]
        print(f"\n2G TCP UL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps

    def test_udp_downlink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "DL", "UDP", 10)
        (run_dir / "iperf_2g_udp_dl.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["2G_UDP_DL"]
        print(f"\n2G UDP DL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps


@pytest.mark.usefixtures("iperf_server_on_dut")
class TestThroughput5G:
    """5 GHz throughput over WiFi RF link."""

    @pytest.fixture(autouse=True, scope="class")
    def wifi_5g(self, bpi_ssh, cfg, dut_ssh):
        _ensure_iperf_server(dut_ssh)
        wifi_ip = _wifi_connect(bpi_ssh, cfg, "5G")
        self.__class__._wifi_ip = wifi_ip
        yield
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_tcp_downlink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "DL", "TCP", 10)
        (run_dir / "iperf_5g_tcp_dl.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["5G_TCP_DL"]
        print(f"\n5G TCP DL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps, \
            f"5G TCP DL below minimum: {result['mbps']:.1f} < {min_mbps} Mbps"

    def test_tcp_uplink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "UL", "TCP", 10)
        (run_dir / "iperf_5g_tcp_ul.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["5G_TCP_UL"]
        print(f"\n5G TCP UL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps

    def test_udp_downlink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "DL", "UDP", 10)
        (run_dir / "iperf_5g_udp_dl.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["5G_UDP_DL"]
        print(f"\n5G UDP DL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps


@pytest.mark.usefixtures("iperf_server_on_dut")
class TestThroughput6G:
    """6 GHz throughput over WiFi RF link (WPA3/SAE)."""

    @pytest.fixture(autouse=True, scope="class")
    def wifi_6g(self, bpi_ssh, cfg, dut_ssh):
        _ensure_iperf_server(dut_ssh)
        wifi_ip = _wifi_connect(bpi_ssh, cfg, "6G")
        self.__class__._wifi_ip = wifi_ip
        yield
        _restore_all_wifi_ifaces(bpi_ssh, cfg)

    def test_tcp_downlink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "DL", "TCP", 10)
        (run_dir / "iperf_6g_tcp_dl.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["6G_TCP_DL"]
        print(f"\n6G TCP DL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps, \
            f"6G TCP DL below minimum: {result['mbps']:.1f} < {min_mbps} Mbps"

    def test_tcp_uplink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "UL", "TCP", 10)
        (run_dir / "iperf_6g_tcp_ul.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["6G_TCP_UL"]
        print(f"\n6G TCP UL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps

    def test_udp_downlink(self, bpi_ssh, cfg, run_dir):
        result = _run_iperf(bpi_ssh, cfg.get("dut.host"), self._wifi_ip, "DL", "UDP", 10)
        (run_dir / "iperf_6g_udp_dl.json").write_text(json.dumps(result["raw"], indent=2))
        min_mbps = THROUGHPUT_MIN["6G_UDP_DL"]
        print(f"\n6G UDP DL: {result['mbps']:.1f} Mbps (min: {min_mbps})")
        assert result["mbps"] >= min_mbps
