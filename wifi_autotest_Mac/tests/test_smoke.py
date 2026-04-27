"""
tests/test_smoke.py
-------------------
Smoke tests — verify the testbed itself is healthy before running any real test.
These must all PASS before you trust any other results.
"""
from __future__ import annotations

import pytest


class TestConnectivity:
    """Verify we can reach DUT and BPI-R4 through all expected channels."""

    def test_dut_ssh_alive(self, dut_ssh):
        rc, out, err = dut_ssh.run("uname -a", check=True)
        assert rc == 0
        assert len(out) > 0
        print(f"\nDUT uname: {out.strip()}")

    def test_dut_serial_alive(self, dut_serial):
        """Send Enter to serial, expect some prompt back."""
        dut_serial.send("")  # just a newline
        buf = dut_serial.drain(duration=2.0)
        # Very loose check — some prompt character should appear
        assert any(ch in buf for ch in ("#", "$", ">", "~")), \
            f"No prompt seen on serial. Got: {buf!r}"

    def test_bpi_ssh_alive(self, bpi_ssh):
        rc, out, err = bpi_ssh.run("uname -a", check=True)
        assert rc == 0
        print(f"\nBPI uname: {out.strip()}")

    def test_bpi_has_wifi_iface(self, bpi_ssh, cfg):
        iface = cfg.get("bpi_sta.wifi_iface", "wlan0")
        rc, out, _ = bpi_ssh.run(f"ip link show {iface}")
        assert rc == 0, f"Wireless interface {iface} not found on BPI-R4"
        assert iface in out

    def test_bpi_has_iperf3(self, bpi_ssh):
        rc, out, _ = bpi_ssh.run("iperf3 --version")
        assert rc == 0, "iperf3 not installed on BPI-R4"
        print(f"\nBPI iperf3: {out.strip().splitlines()[0]}")


class TestDUTBasics:
    """Verify DUT is in a sane state."""

    def test_dut_uptime_positive(self, dut_ssh):
        rc, out, _ = dut_ssh.run("cat /proc/uptime", check=True)
        uptime_sec = float(out.split()[0])
        assert uptime_sec > 0
        print(f"\nDUT uptime: {uptime_sec:.1f}s")

    def test_dut_wifi_radios_present(self, dut_ssh):
        """Expect at least one PHY interface."""
        rc, out, _ = dut_ssh.run("iw dev 2>/dev/null || wl -a wlan0 status 2>/dev/null || echo none")
        assert "phy" in out.lower() or "wlan" in out.lower() or "wl" in out.lower(), \
            f"No WiFi radio detected on DUT. Output: {out}"

    def test_dut_memory_ok(self, dut_ssh):
        """Fail if less than 5% RAM free — likely memory leak from previous run."""
        rc, out, _ = dut_ssh.run("cat /proc/meminfo", check=True)
        mem = {}
        for line in out.splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                try:
                    mem[parts[0].strip()] = int(parts[1].strip().split()[0])
                except ValueError:
                    pass
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", mem.get("MemFree", 0))
        assert total > 0, "Could not read MemTotal"
        free_pct = 100.0 * avail / total
        print(f"\nDUT memory: {avail/1024:.0f} MiB free / {total/1024:.0f} MiB total ({free_pct:.1f}%)")
        assert free_pct > 5.0, f"DUT memory low: {free_pct:.1f}% free"
