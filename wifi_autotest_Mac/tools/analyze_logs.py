#!/usr/bin/env python3
"""
analyze_logs.py
---------------
Post-test data collection: parse failures from junit.xml, SSH into DUT/BPI
to collect live diagnostics, and write structured JSON files for AI analysis.

AI analysis is performed separately by Claude Code (claude --print) in run_all.sh.

Usage:
    python analyze_logs.py runs/20260420-143012
    python analyze_logs.py runs/latest
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from lib.devices import Config, SSHDevice


# ---------------------------------------------------------------------------
# Parse junit.xml for failures
# ---------------------------------------------------------------------------
def parse_junit_failures(run_dir: Path) -> list[dict]:
    junit = run_dir / "junit.xml"
    if not junit.exists():
        return []
    try:
        tree = ET.parse(junit)
    except ET.ParseError:
        return []
    failures = []
    for tc in tree.iter("testcase"):
        for fail in tc.findall("failure"):
            failures.append({
                "name": tc.get("name", "?"),
                "classname": tc.get("classname", "?"),
                "message": fail.get("message", ""),
                "text": (fail.text or "").strip()[:2000],
            })
    return failures


# ---------------------------------------------------------------------------
# Live diagnostics via SSH
# ---------------------------------------------------------------------------
DUT_DIAG_CMDS = [
    ("uptime",          "uptime"),
    ("iw_dev",          "iw dev"),
    ("wifi_status",     "ubus call network.wireless status 2>/dev/null || echo 'ubus not available'"),
    ("uci_wireless",    "uci show wireless 2>/dev/null | head -60"),
    ("iperf_running",   "ps | grep iperf3 | grep -v grep || echo 'iperf3 not running'"),
    ("iperf_port",      "netstat -ln 2>/dev/null | grep :5201 || ss -ln 2>/dev/null | grep :5201 || echo ':5201 not listening'"),
    ("iperf_log",       "tail -20 /tmp/iperf3.log 2>/dev/null || echo 'no iperf3.log'"),
    ("dmesg_wifi",      "dmesg | grep -iE 'wifi|wlan|ath|qca|EHT|HE |VHT|HT |radar|dfs|csa' | tail -40"),
    ("logread_hostapd", "logread 2>/dev/null | grep -iE 'hostapd|wpa_supplicant|assoc|auth|disassoc' | tail -40 || tail -n40 /var/log/messages 2>/dev/null || echo 'no syslog'"),
    ("iw_phy",          "iw phy 2>/dev/null | head -60 || echo 'iw phy unavailable'"),
]

BPI_DIAG_CMDS = [
    ("iw_dev",           "iw dev"),
    ("supplicant_state", "for iface in apcli0 apclii0 apclix0; do echo \"=== $iface ===\"; wpa_cli -i $iface status 2>/dev/null || echo 'no supplicant'; done"),
    ("dmesg_wifi",       "dmesg | grep -iE 'wifi|mt76|mt7996|assoc|auth|scan|EBUSY' | tail -30"),
    ("iw_link",          "for iface in apcli0 apclii0 apclix0; do echo \"=== $iface ===\"; iw dev $iface link 2>/dev/null || echo 'no link'; done"),
]


def _run_diag(ssh: SSHDevice, label: str, cmd: str) -> dict:
    try:
        rc, out, err = ssh.run(cmd, timeout=15)
        return {"label": label, "cmd": cmd, "rc": rc, "out": (out + err).strip()}
    except Exception as exc:
        return {"label": label, "cmd": cmd, "rc": -1, "out": f"ERROR: {exc}"}


def collect_live_diagnostics(cfg: Config, failures: list[dict]) -> dict:
    result = {"failures": failures, "dut": [], "bpi": []}

    print("[+] Connecting to DUT for live diagnostics...")
    dut = SSHDevice(
        name="DUT",
        host=cfg.get("dut.host"),
        user=cfg.get("dut.ssh_user", "root"),
    )
    try:
        dut.connect()
        for label, cmd in DUT_DIAG_CMDS:
            r = _run_diag(dut, label, cmd)
            result["dut"].append(r)
            print(f"  [DUT] {label}: {len(r['out'])} chars")
    except Exception as e:
        result["dut"].append({"label": "connect_error", "cmd": "", "rc": -1, "out": str(e)})
        print(f"  [!] Could not connect to DUT: {e}")
    finally:
        try:
            dut.close()
        except Exception:
            pass

    print("[+] Connecting to BPI for live diagnostics...")
    bpi = SSHDevice(
        name="BPI",
        host=cfg.get("bpi_sta.host"),
        user=cfg.get("bpi_sta.ssh_user", "root"),
    )
    try:
        bpi.connect()
        for label, cmd in BPI_DIAG_CMDS:
            r = _run_diag(bpi, label, cmd)
            result["bpi"].append(r)
            print(f"  [BPI] {label}: {len(r['out'])} chars")
    except Exception as e:
        result["bpi"].append({"label": "connect_error", "cmd": "", "rc": -1, "out": str(e)})
        print(f"  [!] Could not connect to BPI: {e}")
    finally:
        try:
            bpi.close()
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def resolve_run_dir(arg: str) -> Path:
    p = Path(arg)
    if arg.endswith("latest") or arg == "latest":
        base = p.parent if p.name == "latest" else Path("runs")
        runs = sorted([d for d in base.iterdir() if d.is_dir()])
        if not runs:
            sys.exit(f"No run directories found under {base}")
        return runs[-1]
    if not p.exists():
        sys.exit(f"Run directory not found: {p}")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir", help="Path to run directory (or 'runs/latest')")
    ap.add_argument("--config", default="config.yaml")
    args = ap.parse_args()

    run_dir = resolve_run_dir(args.run_dir)
    print(f"[+] Collecting diagnostics for {run_dir}")

    cfg_path = Path(args.config)
    cfg = Config.load(cfg_path) if cfg_path.exists() else Config(raw={})

    failures = parse_junit_failures(run_dir)
    print(f"[+] Failed tests: {len(failures)}")
    for f in failures:
        print(f"    - {f['classname']}.{f['name']}: {f['message'][:80]}")

    if not failures:
        print("[+] No failures — skipping live diagnostics.")
        return

    diag = collect_live_diagnostics(cfg, failures)
    out = run_dir / "live_diagnostics.json"
    out.write_text(json.dumps(diag, indent=2))
    print(f"[+] Wrote {out}")


if __name__ == "__main__":
    main()
