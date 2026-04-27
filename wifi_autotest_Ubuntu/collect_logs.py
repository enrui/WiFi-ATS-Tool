#!/usr/bin/env python3
"""
collect_logs.py
---------------
Pull the latest logs from DUT (dmesg, syslog) and BPI (if relevant) into
the current run directory. Usually called from pytest teardown, but also
runnable standalone for manual log grabs.

Usage:
    python collect_logs.py --run runs/20260420-143012
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.devices import Config, make_dut_ssh, make_bpi_ssh


DUT_LOG_COMMANDS = {
    "dut_dmesg.log":       "dmesg -T 2>/dev/null || dmesg",
    "dut_syslog.log":      "logread 2>/dev/null || tail -n 2000 /var/log/syslog 2>/dev/null || tail -n 2000 /var/log/messages 2>/dev/null || echo '(no syslog available)'",
    "dut_hostapd.log":     "logread | grep -i hostapd 2>/dev/null || grep -i hostapd /var/log/syslog 2>/dev/null | tail -200 || echo '(no hostapd log)'",
    "dut_iw_dev.txt":      "iw dev 2>/dev/null && echo '---' && iw phy 2>/dev/null",
    "dut_uptime.txt":      "uptime && echo '---' && cat /proc/uptime",
    "dut_meminfo.txt":     "cat /proc/meminfo",
    "dut_top.txt":         "top -bn1 2>/dev/null | head -40 || ps -e",
    "dut_netstat.txt":     "netstat -tn 2>/dev/null || ss -tn",
}

BPI_LOG_COMMANDS = {
    "bpi_dmesg.log":       "dmesg -T | tail -500",
    "bpi_syslog.log":      "tail -n 1000 /var/log/syslog 2>/dev/null || journalctl -n 1000 2>/dev/null",
    "bpi_supplicant.log":  "grep -i wpa_supplicant /var/log/syslog 2>/dev/null | tail -200 || journalctl -u wpa_supplicant -n 200 2>/dev/null",
    "bpi_iw_dev.txt":      "iw dev && echo '---' && iw phy",
}


def collect(dev, commands: dict, outdir: Path, prefix: str):
    outdir.mkdir(parents=True, exist_ok=True)
    for filename, cmd in commands.items():
        try:
            rc, out, err = dev.run(cmd, timeout=20)
            content = out or err or "(no output)"
        except Exception as e:
            content = f"(failed to collect: {e})"
        (outdir / filename).write_text(content)
        print(f"  [{prefix}] {filename}  ({len(content):,} bytes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="Run directory to write logs into")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--skip-bpi", action="store_true")
    args = ap.parse_args()

    cfg = Config.load(args.config)
    outdir = Path(args.run)
    outdir.mkdir(parents=True, exist_ok=True)

    # DUT
    print("[+] Collecting DUT logs...")
    dut = make_dut_ssh(cfg)
    try:
        dut.connect()
        collect(dut, DUT_LOG_COMMANDS, outdir, "DUT")
    finally:
        dut.close()

    # BPI
    if not args.skip_bpi:
        print("[+] Collecting BPI-R4 logs...")
        bpi = make_bpi_ssh(cfg)
        try:
            bpi.connect()
            collect(bpi, BPI_LOG_COMMANDS, outdir, "BPI")
        finally:
            bpi.close()

    print(f"[+] Logs written to {outdir}")


if __name__ == "__main__":
    main()
