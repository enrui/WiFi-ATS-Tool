#!/usr/bin/env python3
"""
stability_runner.py
-------------------
2-hour WiFi stability soak test.

What it does every 60 seconds:
  - Verify BPI is still associated to the DUT
  - Run a 30-second iperf3 TCP DL + UL sample
  - Collect DUT: CPU load, memory, top processes, syslog tail, dmesg tail
  - Flag anomalies: WiFi drop, high load, kernel error keywords

Usage:
    python3 tools/stability_runner.py [--band 5G] [--duration 7200] [--interval 60]
    (or via: bash run_stability.sh [--band 5G] [--duration 7200] [--interval 60])

Output:
    Writes to runs/stability-YYYYMMDD-HHMMSS/
      stability.log        ← human-readable per-check log
      stability_data.json  ← structured data for each interval
      stability_report.md  ← final summary
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.devices import Config, make_dut_ssh, make_bpi_ssh
from tests.test_association import _write_wpa_conf, _restore_all_wifi_ifaces, _BAND_CFG

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
IPERF_DURATION   = 25      # seconds per iperf3 sample (DL + UL each)
IPERF_PORT       = 5201
ANOMALY_KEYWORDS = [
    "panic", "kernel bug", "oops", "segfault", "oom-kill",
    "out of memory", "watchdog", "hung task", "call trace",
    "hard lockup", "soft lockup", "rcu stall",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def log(msg: str, file=None):
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    if file:
        file.write(line + "\n")
        file.flush()


def connect_bpi_wifi(bpi_ssh, cfg, band: str) -> bool:
    iface_key, ssid_key, security = _BAND_CFG[band]
    iface = cfg.get(iface_key)
    ssid  = cfg.get(ssid_key)
    psk   = cfg.get("dut.wifi.psk")

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

    for _ in range(30):
        time.sleep(1)
        _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
        if "Connected to" in out:
            bpi_ssh.run(f"udhcpc -i {iface} -t 8 -n 2>&1 || true")
            return True
    return False


def check_wifi(bpi_ssh, iface: str) -> tuple[bool, str]:
    _, out, _ = bpi_ssh.run(f"iw dev {iface} link")
    connected = "Connected to" in out
    bssid = ""
    m = re.search(r"Connected to ([\da-f:]+)", out)
    if m:
        bssid = m.group(1)
    return connected, bssid


def ensure_iperf_server(dut_ssh):
    _, out, _ = dut_ssh.run("ss -ln 2>/dev/null | grep :5201 || netstat -ln 2>/dev/null | grep :5201")
    if ":5201" not in out:
        dut_ssh.run("killall iperf3 2>/dev/null; sleep 0.3; true")
        dut_ssh.run(f"iperf3 -s -p {IPERF_PORT} -D >/tmp/iperf3_stability.log 2>&1")
        time.sleep(1)


def run_iperf_sample(bpi_ssh, dut_ip: str, iface: str) -> dict:
    result = {"dl_mbps": 0.0, "ul_mbps": 0.0, "error": ""}
    t = IPERF_DURATION

    # TCP Downlink (server→client)
    _, out, _ = bpi_ssh.run(
        f"iperf3 -c {dut_ip} -p {IPERF_PORT} -t {t} -J 2>/dev/null",
        timeout=(t + 15) * 1000
    )
    try:
        data = json.loads(out)
        s = data["end"].get("sum_received", data["end"].get("sum", {}))
        result["dl_mbps"] = round(s["bits_per_second"] / 1e6, 1)
    except Exception as e:
        result["error"] += f"DL:{e} "

    # TCP Uplink (client→server)
    _, out, _ = bpi_ssh.run(
        f"iperf3 -c {dut_ip} -p {IPERF_PORT} -t {t} -R -J 2>/dev/null",
        timeout=(t + 15) * 1000
    )
    try:
        data = json.loads(out)
        s = data["end"].get("sum_received", data["end"].get("sum", {}))
        result["ul_mbps"] = round(s["bits_per_second"] / 1e6, 1)
    except Exception as e:
        result["error"] += f"UL:{e} "

    return result


def collect_dut_metrics(dut_ssh) -> dict:
    metrics = {}

    _, out, _ = dut_ssh.run("cat /proc/loadavg")
    metrics["loadavg"] = out.strip()
    parts = out.split()
    metrics["load_1m"] = float(parts[0]) if parts else 0.0

    _, out, _ = dut_ssh.run("free | awk 'NR==2{printf \"%.0f\", $3/$2*100}'")
    try:
        metrics["mem_pct"] = int(out.strip())
    except Exception:
        metrics["mem_pct"] = -1

    _, out, _ = dut_ssh.run("ps 2>/dev/null | sort -rn -k3 | head -8")
    metrics["top_procs"] = out.strip()

    _, out, _ = dut_ssh.run("logread 2>/dev/null | tail -20")
    metrics["syslog_tail"] = out.strip()

    _, out, _ = dut_ssh.run("dmesg 2>/dev/null | tail -15")
    metrics["dmesg_tail"] = out.strip()

    # Anomaly scan
    combined = (metrics["syslog_tail"] + "\n" + metrics["dmesg_tail"]).lower()
    found = [kw for kw in ANOMALY_KEYWORDS if kw in combined]
    metrics["anomalies"] = found

    return metrics


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="WiFi 2-hour stability soak test")
    parser.add_argument("--band",     default="5G",  choices=["2G", "5G", "6G"])
    parser.add_argument("--duration", default=7200,  type=int, help="Total seconds (default 7200)")
    parser.add_argument("--interval", default=60,    type=int, help="Check interval in seconds (default 60)")
    args = parser.parse_args()

    cfg = Config.load("config.yaml")

    run_dir = Path("runs") / f"stability-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"Run dir: {run_dir}", flush=True)

    log_path  = run_dir / "stability.log"
    data_path = run_dir / "stability_data.json"

    iface = cfg.get(f"bpi_sta.wifi_iface_{args.band.lower()}")
    dut_ip = cfg.get("dut.host")

    dut_ssh = make_dut_ssh(cfg)
    bpi_ssh = make_bpi_ssh(cfg)
    dut_ssh.connect()
    bpi_ssh.connect()

    results = []
    disconnects = 0
    anomaly_events = []
    iperf_failures = 0

    with open(log_path, "w") as logf:
        # ------------------------------------------------------------------ #
        # Initial WiFi association
        # ------------------------------------------------------------------ #
        log(f"=== WiFi Stability Soak Test ===", logf)
        log(f"Band: {args.band} | Iface: {iface} | Duration: {args.duration}s | Interval: {args.interval}s", logf)
        log(f"DUT: {dut_ip}", logf)
        log("", logf)
        log("Connecting BPI to DUT WiFi...", logf)

        if not connect_bpi_wifi(bpi_ssh, cfg, args.band):
            log("FATAL: initial WiFi association failed. Abort.", logf)
            sys.exit(1)

        log(f"Associated on {iface}. Starting iperf3 server on DUT...", logf)
        ensure_iperf_server(dut_ssh)
        log("Ready. Entering monitoring loop.\n", logf)

        # ------------------------------------------------------------------ #
        # Monitoring loop
        # ------------------------------------------------------------------ #
        start_time = time.monotonic()
        end_time   = start_time + args.duration
        check_num  = 0

        while time.monotonic() < end_time:
            loop_start = time.monotonic()
            check_num += 1
            elapsed = int(loop_start - start_time)
            remaining = int(end_time - loop_start)
            eta = datetime.now() + timedelta(seconds=remaining)

            log(f"--- Check #{check_num:03d}  elapsed={elapsed}s  remaining={remaining}s  ETA={eta.strftime('%H:%M:%S')} ---", logf)

            entry = {
                "check": check_num,
                "elapsed_s": elapsed,
                "time": ts(),
                "wifi_ok": False,
                "bssid": "",
                "dl_mbps": 0.0,
                "ul_mbps": 0.0,
                "load_1m": 0.0,
                "mem_pct": -1,
                "anomalies": [],
                "notes": [],
            }

            # 1. WiFi check
            connected, bssid = check_wifi(bpi_ssh, iface)
            entry["wifi_ok"] = connected
            entry["bssid"] = bssid

            if not connected:
                disconnects += 1
                log(f"  ⚠  WiFi DISCONNECTED (#{disconnects}). Attempting reconnect...", logf)
                entry["notes"].append(f"wifi_drop#{disconnects}")
                if not connect_bpi_wifi(bpi_ssh, cfg, args.band):
                    log("  ✗  Reconnect FAILED. Continuing monitoring.", logf)
                    entry["notes"].append("reconnect_failed")
                else:
                    ensure_iperf_server(dut_ssh)
                    log("  ✓  Reconnected.", logf)
                    entry["notes"].append("reconnected")
            else:
                log(f"  WiFi: OK  BSSID={bssid}", logf)

            # 2. iperf3 traffic sample (only if connected)
            if entry["wifi_ok"] or "reconnected" in entry["notes"]:
                ensure_iperf_server(dut_ssh)
                log(f"  iperf3: running {IPERF_DURATION}s DL + {IPERF_DURATION}s UL...", logf)
                iperf = run_iperf_sample(bpi_ssh, dut_ip, iface)
                entry["dl_mbps"] = iperf["dl_mbps"]
                entry["ul_mbps"] = iperf["ul_mbps"]
                if iperf["error"]:
                    iperf_failures += 1
                    entry["notes"].append(f"iperf_err:{iperf['error'].strip()}")
                    log(f"  iperf3: DL={iperf['dl_mbps']} Mbps  UL={iperf['ul_mbps']} Mbps  ⚠ {iperf['error']}", logf)
                else:
                    log(f"  iperf3: DL={iperf['dl_mbps']} Mbps  UL={iperf['ul_mbps']} Mbps", logf)

            # 3. DUT metrics
            metrics = collect_dut_metrics(dut_ssh)
            entry["load_1m"] = metrics["load_1m"]
            entry["mem_pct"] = metrics["mem_pct"]
            entry["anomalies"] = metrics["anomalies"]

            load_warn = " ⚠ HIGH" if metrics["load_1m"] > 2.0 else ""
            mem_warn  = " ⚠ HIGH" if metrics["mem_pct"] > 85 else ""
            log(f"  DUT: load={metrics['loadavg']}  mem={metrics['mem_pct']}%{mem_warn}{load_warn}", logf)

            if metrics["load_1m"] > 2.0:
                entry["notes"].append(f"high_load:{metrics['load_1m']}")

            if metrics["anomalies"]:
                log(f"  DUT: ‼ ANOMALY KEYWORDS: {metrics['anomalies']}", logf)
                anomaly_events.append({
                    "check": check_num,
                    "elapsed_s": elapsed,
                    "keywords": metrics["anomalies"],
                    "dmesg_tail": metrics["dmesg_tail"][-500:],
                })
                entry["notes"].append(f"anomaly:{metrics['anomalies']}")

            if metrics["top_procs"]:
                logf.write("  [top procs]\n")
                for line in metrics["top_procs"].splitlines():
                    logf.write(f"    {line}\n")
                logf.flush()

            results.append(entry)

            # Save incremental JSON
            with open(data_path, "w") as jf:
                json.dump({"results": results, "anomaly_events": anomaly_events}, jf, indent=2)

            # Sleep until next interval
            elapsed_this_check = time.monotonic() - loop_start
            sleep_time = max(0, args.interval - elapsed_this_check)
            if sleep_time > 0 and time.monotonic() + sleep_time < end_time:
                log(f"  (sleeping {sleep_time:.0f}s until next check)\n", logf)
                time.sleep(sleep_time)

        # ------------------------------------------------------------------ #
        # Final summary
        # ------------------------------------------------------------------ #
        log("\n" + "=" * 60, logf)
        log("STABILITY TEST COMPLETE", logf)
        log("=" * 60, logf)

        dl_vals = [r["dl_mbps"] for r in results if r["dl_mbps"] > 0]
        ul_vals = [r["ul_mbps"] for r in results if r["ul_mbps"] > 0]
        wifi_drops = sum(1 for r in results if not r["wifi_ok"])

        summary = {
            "band": args.band,
            "duration_s": args.duration,
            "checks": check_num,
            "wifi_disconnects": disconnects,
            "iperf_failures": iperf_failures,
            "anomaly_count": len(anomaly_events),
            "dl_avg_mbps": round(sum(dl_vals) / len(dl_vals), 1) if dl_vals else 0,
            "dl_min_mbps": round(min(dl_vals), 1) if dl_vals else 0,
            "ul_avg_mbps": round(sum(ul_vals) / len(ul_vals), 1) if ul_vals else 0,
            "ul_min_mbps": round(min(ul_vals), 1) if ul_vals else 0,
        }

        verdict = "PASS" if disconnects == 0 and len(anomaly_events) == 0 else "FAIL"

        log(f"Verdict       : {verdict}", logf)
        log(f"Band          : {args.band}", logf)
        log(f"Total checks  : {check_num}", logf)
        log(f"WiFi drops    : {disconnects}", logf)
        log(f"iperf failures: {iperf_failures}", logf)
        log(f"Anomalies     : {len(anomaly_events)}", logf)
        log(f"DL throughput : avg={summary['dl_avg_mbps']} Mbps  min={summary['dl_min_mbps']} Mbps", logf)
        log(f"UL throughput : avg={summary['ul_avg_mbps']} Mbps  min={summary['ul_min_mbps']} Mbps", logf)

        if anomaly_events:
            log("\nAnomaly events:", logf)
            for ev in anomaly_events:
                log(f"  Check #{ev['check']} ({ev['elapsed_s']}s): {ev['keywords']}", logf)

        # Write markdown report
        report_path = run_dir / "stability_report.md"
        with open(report_path, "w") as rf:
            rf.write(f"# WiFi Stability Report\n\n")
            rf.write(f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            rf.write(f"**Band**: {args.band}  |  **Duration**: {args.duration//60} min  |  **Interval**: {args.interval}s\n\n")
            rf.write(f"## Verdict: {verdict}\n\n")
            rf.write(f"| Metric | Value |\n|--------|-------|\n")
            rf.write(f"| Total checks | {check_num} |\n")
            rf.write(f"| WiFi disconnections | {disconnects} |\n")
            rf.write(f"| iperf3 failures | {iperf_failures} |\n")
            rf.write(f"| DUT anomalies detected | {len(anomaly_events)} |\n")
            rf.write(f"| TCP DL avg / min | {summary['dl_avg_mbps']} / {summary['dl_min_mbps']} Mbps |\n")
            rf.write(f"| TCP UL avg / min | {summary['ul_avg_mbps']} / {summary['ul_min_mbps']} Mbps |\n\n")

            if anomaly_events:
                rf.write("## Anomaly Events\n\n")
                for ev in anomaly_events:
                    rf.write(f"### Check #{ev['check']} (t={ev['elapsed_s']}s)\n")
                    rf.write(f"Keywords: `{ev['keywords']}`\n\n")
                    rf.write(f"```\n{ev['dmesg_tail']}\n```\n\n")

            rf.write("## Throughput Over Time\n\n")
            rf.write("| Check | Elapsed | WiFi | DL Mbps | UL Mbps | Load | Notes |\n")
            rf.write("|-------|---------|------|---------|---------|------|-------|\n")
            for r in results:
                wifi_s = "✓" if r["wifi_ok"] else "✗"
                notes_s = ", ".join(r["notes"]) if r["notes"] else ""
                rf.write(f"| {r['check']:03d} | {r['elapsed_s']}s | {wifi_s} | "
                         f"{r['dl_mbps']} | {r['ul_mbps']} | {r['load_1m']} | {notes_s} |\n")

        log(f"\nReport: {report_path}", logf)
        log(f"Data  : {data_path}", logf)

    # Save final JSON
    with open(data_path, "w") as jf:
        json.dump({"summary": summary, "results": results, "anomaly_events": anomaly_events}, jf, indent=2)

    dut_ssh.close()
    bpi_ssh.close()

    sys.exit(0 if verdict == "PASS" else 1)


if __name__ == "__main__":
    main()
