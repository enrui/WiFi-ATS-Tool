"""
generate_report.py
------------------
Generate a concise single-page HTML summary report from a test run directory.

Sources:
  junit.xml           — test names, pass/fail/error, duration
  iperf_*.json        — throughput measurements (Mbps)
  claude_report.json  — AI analysis (optional)

Usage:
  python generate_report.py runs/20260425-120000
  python generate_report.py runs/latest          # symlink or newest dir
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_junit(path: Path) -> dict:
    tree = ET.parse(path)
    suite = tree.find(".//testsuite")
    if suite is None:
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "duration": 0, "cases": []}

    total    = int(suite.get("tests",   0))
    failures = int(suite.get("failures", 0))
    errors   = int(suite.get("errors",   0))
    passed   = total - failures - errors
    duration = float(suite.get("time",   0))

    cases = []
    for tc in suite.findall("testcase"):
        failure = tc.find("failure")
        error   = tc.find("error")
        if error is not None:
            status  = "ERROR"
            message = error.get("message", "")
        elif failure is not None:
            status  = "FAIL"
            message = failure.get("message", "")
        else:
            status  = "PASS"
            message = ""
        cases.append({
            "class": tc.get("classname", ""),
            "name":  tc.get("name", ""),
            "time":  float(tc.get("time", 0)),
            "status": status,
            "message": message,
        })
    return {
        "total": total, "passed": passed, "failed": failures,
        "errors": errors, "duration": duration, "cases": cases,
    }


def _parse_iperf_files(run_dir: Path) -> dict:
    """Return {band: {direction: {proto: mbps}}} from iperf_*.json files."""
    results: dict = {}
    for f in sorted(run_dir.glob("iperf_*.json")):
        # filename: iperf_5g_tcp_dl.json  → band=5g, proto=tcp, dir=dl
        parts = f.stem.split("_")  # ['iperf','5g','tcp','dl']
        if len(parts) != 4:
            continue
        _, band, proto, direction = parts
        band      = band.upper()   # "5G"
        proto     = proto.upper()  # "TCP"
        direction = direction.upper()  # "DL"
        try:
            data = json.loads(f.read_text())
            end  = data.get("end", {})
            s    = end.get("sum_sent", end.get("sum", {}))
            mbps = s.get("bits_per_second", 0) / 1e6
        except Exception:
            mbps = None
        results.setdefault(band, {}).setdefault(direction, {})[proto] = mbps
    return results


def _parse_claude_md(run_dir: Path) -> str | None:
    p = run_dir / "claude_report.md"
    if not p.exists():
        return None
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return None


def _parse_live_diag(run_dir: Path) -> dict | None:
    p = run_dir / "live_diagnostics.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# HTML generation
# ---------------------------------------------------------------------------

_STATUS_STYLE = {
    "PASS":  ("✓", "#16a34a", "#f0fdf4"),
    "FAIL":  ("✗", "#dc2626", "#fef2f2"),
    "ERROR": ("!", "#d97706", "#fffbeb"),
}

_SEVERITY_COLOR = {
    "critical": "#dc2626",
    "high":     "#d97706",
    "medium":   "#ca8a04",
    "low":      "#16a34a",
    "none":     "#6b7280",
}

def _badge(status: str) -> str:
    icon, color, _ = _STATUS_STYLE.get(status, ("?", "#6b7280", "#f9fafb"))
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:12px;'
            f'background:{color};color:#fff;font-weight:700;font-size:0.8em">'
            f'{icon} {status}</span>')


def _throughput_table(iperf: dict) -> str:
    if not iperf:
        return "<p style='color:#6b7280'>No throughput data found.</p>"

    bands = ["2G", "5G", "6G"]
    rows = ""
    for band in bands:
        if band not in iperf:
            continue
        band_data = iperf[band]
        for direction in ("DL", "UL"):
            if direction not in band_data:
                continue
            for proto in ("TCP", "UDP"):
                mbps = band_data[direction].get(proto)
                if mbps is None:
                    cell = '<span style="color:#9ca3af">—</span>'
                elif mbps >= 1000:
                    cell = f'<span style="color:#16a34a;font-weight:600">{mbps:.0f} Mbps</span>'
                elif mbps >= 100:
                    cell = f'<span style="color:#2563eb;font-weight:600">{mbps:.0f} Mbps</span>'
                else:
                    cell = f'<span style="color:#d97706;font-weight:600">{mbps:.0f} Mbps</span>'
                rows += (f"<tr><td>{band}</td><td>{direction}</td>"
                         f"<td>{proto}</td><td>{cell}</td></tr>")
    return f"""
<table>
  <thead><tr><th>Band</th><th>Direction</th><th>Protocol</th><th>Throughput</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _md_to_html(md: str) -> str:
    """Minimal Markdown-to-HTML: headings, bold, code blocks, lists."""
    import re
    html = ""
    in_code = False
    for line in md.splitlines():
        if line.startswith("```"):
            if in_code:
                html += "</pre>\n"
                in_code = False
            else:
                html += "<pre style='background:#f8fafc;padding:10px;border-radius:4px;font-size:0.82em;overflow-x:auto;white-space:pre-wrap'>"
                in_code = True
            continue
        if in_code:
            html += line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") + "\n"
            continue
        # Headings
        m = re.match(r'^(#{1,3})\s+(.*)', line)
        if m:
            level = len(m.group(1)) + 1  # h2..h4
            html += f"<h{level} style='margin:16px 0 6px;color:#374151'>{m.group(2)}</h{level}>\n"
            continue
        # Bullet
        m = re.match(r'^[-*]\s+(.*)', line)
        if m:
            content = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', m.group(1))
            content = re.sub(r'`(.*?)`', r'<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px">\1</code>', content)
            html += f"<li style='margin:3px 0'>{content}</li>\n"
            continue
        # Bold inline
        line = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', line)
        line = re.sub(r'`(.*?)`', r'<code style="background:#f1f5f9;padding:1px 4px;border-radius:3px">\1</code>', line)
        html += f"<p style='margin:4px 0'>{line}</p>\n" if line.strip() else "<br>\n"
    if in_code:
        html += "</pre>\n"
    return html


def _claude_section(ai_md: str | None) -> str:
    if not ai_md:
        return ""
    return f"""
<section>
  <h2>AI Analysis (Claude Code)</h2>
  <div style="background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:16px 20px">
    {_md_to_html(ai_md)}
  </div>
</section>"""


def _diagnostics_section(diag: dict | None) -> str:
    if not diag:
        return ""
    rows = ""
    for device, results in (("DUT", diag.get("dut", [])), ("BPI-R4", diag.get("bpi", []))):
        for r in results:
            if not r.get("cmd"):
                continue
            out = r.get("out", "").strip()[:800]
            out_html = (f"<pre style='margin:4px 0 0;background:#f8fafc;padding:8px;border-radius:4px;"
                        f"font-size:0.78em;overflow-x:auto;white-space:pre-wrap'>{out}</pre>"
                        if out else "")
            rows += (f'<tr><td style="white-space:nowrap;color:#6b7280">{device}</td>'
                     f'<td><code style="font-size:0.82em">{r["cmd"]}</code>{out_html}</td></tr>')
    if not rows:
        return ""
    return f"""
<section>
  <h2>Live Diagnostics (post-failure SSH)</h2>
  <table>
    <thead><tr><th style="width:70px">Device</th><th>Command &amp; Output</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>"""


def _group_label(classname: str, name: str) -> str:
    """Return a readable display name from classname + test name."""
    label = classname.split(".")[-1] if classname else ""
    if label.startswith("TestThroughput"):
        label = label.replace("TestThroughput", "") + " throughput"
    return f"{label} / {name}" if label else name


def generate_html(run_dir: Path) -> str:
    stamp = run_dir.name  # e.g. 20260425-120000
    try:
        dt = datetime.strptime(stamp, "%Y%m%d-%H%M%S")
        run_time = dt.strftime("%Y-%m-%d  %H:%M:%S")
    except ValueError:
        run_time = stamp

    junit_path = run_dir / "junit.xml"
    if not junit_path.exists():
        sys.exit(f"ERROR: {junit_path} not found")

    junit  = _parse_junit(junit_path)
    iperf  = _parse_iperf_files(run_dir)
    ai     = _parse_claude_md(run_dir)
    diag   = _parse_live_diag(run_dir)

    overall_status = "PASS" if (junit["failed"] + junit["errors"]) == 0 else "FAIL"
    _, ov_color, ov_bg = _STATUS_STYLE[overall_status]
    duration_str = f"{junit['duration']:.0f}s"

    # --- test cases table ---
    rows = ""
    for c in junit["cases"]:
        icon, color, bg = _STATUS_STYLE[c["status"]]
        label = _group_label(c["class"], c["name"])
        msg_html = (f"<div style='margin-top:4px;font-size:0.8em;color:#6b7280;"
                    f"font-family:monospace;white-space:pre-wrap'>{c['message'][:200]}</div>"
                    if c["message"] else "")
        rows += (f'<tr style="background:{bg}">'
                 f'<td>{_badge(c["status"])}</td>'
                 f'<td>{label}{msg_html}</td>'
                 f'<td style="text-align:right;color:#6b7280">{c["time"]:.1f}s</td>'
                 f'</tr>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WiFi Test Report — {stamp}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          font-size: 14px; color: #111; background: #f8fafc; padding: 24px; }}
  .page {{ max-width: 900px; margin: 0 auto; background: #fff;
           border-radius: 12px; box-shadow: 0 2px 16px #0001; padding: 32px; }}
  h1   {{ font-size: 1.4em; margin-bottom: 4px; }}
  h2   {{ font-size: 1.1em; margin: 24px 0 12px; color: #374151; border-bottom: 2px solid #e5e7eb; padding-bottom: 6px; }}
  h3   {{ font-size: 0.95em; color: #374151; }}
  section {{ margin-bottom: 8px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 8px; font-size: 0.9em; }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #e5e7eb; }}
  thead th {{ background: #f1f5f9; font-weight: 600; color: #374151; }}
  tr:last-child td {{ border-bottom: none; }}
  .stat-row {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 20px; }}
  .stat-card {{ flex: 1; min-width: 110px; background: #f8fafc; border: 1px solid #e5e7eb;
                border-radius: 8px; padding: 12px 16px; }}
  .stat-label {{ font-size: 0.75em; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }}
  .stat-value {{ font-size: 1.6em; font-weight: 700; margin-top: 4px; }}
  .print-btn {{ float: right; padding: 6px 16px; background: #2563eb; color: #fff;
                border: none; border-radius: 6px; cursor: pointer; font-size: 0.85em; }}
  @media print {{
    body {{ background: #fff; padding: 0; }}
    .page {{ box-shadow: none; padding: 0; }}
    .print-btn {{ display: none; }}
  }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:20px">
    <div>
      <h1>WiFi Test Report</h1>
      <div style="color:#6b7280;font-size:0.85em;margin-top:4px">{run_time}</div>
    </div>
    <div style="text-align:right">
      <div style="font-size:2em;font-weight:800;color:{ov_color}">{overall_status}</div>
      <button class="print-btn" onclick="window.print()">⬇ Print / Save PDF</button>
    </div>
  </div>

  <!-- Summary stats -->
  <section>
    <div class="stat-row">
      <div class="stat-card">
        <div class="stat-label">Total</div>
        <div class="stat-value">{junit['total']}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Passed</div>
        <div class="stat-value" style="color:#16a34a">{junit['passed']}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Failed</div>
        <div class="stat-value" style="color:#dc2626">{junit['failed']}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Errors</div>
        <div class="stat-value" style="color:#d97706">{junit['errors']}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Duration</div>
        <div class="stat-value" style="font-size:1.2em;padding-top:6px">{duration_str}</div>
      </div>
    </div>
  </section>

  <!-- Test results -->
  <section>
    <h2>Test Results</h2>
    <table>
      <thead><tr><th style="width:90px">Status</th><th>Test</th><th style="width:70px">Time</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </section>

  <!-- Throughput -->
  {"<section><h2>Throughput</h2>" + _throughput_table(iperf) + "</section>" if iperf else ""}

  <!-- Live Diagnostics -->
  {_diagnostics_section(diag)}

  <!-- AI Analysis -->
  {_claude_section(ai)}

  <div style="margin-top:24px;font-size:0.75em;color:#9ca3af;text-align:right">
    Generated by wifi_autotest · Run: {stamp}
  </div>
</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default to newest run
        runs = sorted(Path("runs").iterdir())
        if not runs:
            sys.exit("No runs found")
        run_dir = runs[-1]
    else:
        run_dir = Path(sys.argv[1])
        if not run_dir.exists():
            sys.exit(f"Run directory not found: {run_dir}")

    html = generate_html(run_dir)
    out  = run_dir / "summary_report.html"
    out.write_text(html, encoding="utf-8")
    print(f"Report saved: {out}")
    print(f"Open: open '{out}'")
