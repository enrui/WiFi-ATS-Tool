#!/usr/bin/env python3
"""
analyze_logs.py
---------------
Reads logs from a test run directory, sends them to Claude, and writes a
structured JSON report + a human-readable Markdown summary.

Usage:
    python analyze_logs.py runs/20260420-143012
    python analyze_logs.py runs/latest                # auto-pick newest
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from lib.logtools import preprocess_log, extract_failure_window


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------
def call_claude(system_prompt: str, user_content: str,
                model: str = "claude-opus-4-7",
                max_tokens: int = 4000) -> str:
    """Minimal wrapper around the Anthropic SDK."""
    try:
        import anthropic
    except ImportError:
        sys.exit("Missing 'anthropic' package. Run: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("ANTHROPIC_API_KEY not set in environment.")

    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    # Concatenate text blocks
    return "".join(
        block.text for block in msg.content
        if getattr(block, "type", "") == "text"
    )


# ---------------------------------------------------------------------------
# Build the user message
# ---------------------------------------------------------------------------
def build_user_payload(run_dir: Path) -> str:
    """Gather metadata + logs into a single Claude-friendly message."""
    parts = []

    # Test result summary (pytest JSON report if present)
    pytest_json = run_dir / "pytest_report.json"
    if pytest_json.exists():
        parts.append("## Pytest Result Summary\n")
        parts.append("```json\n" + pytest_json.read_text()[:10_000] + "\n```\n")

    # DUT serial log
    serial_log = run_dir / "dut_serial.log"
    if serial_log.exists():
        parts.append("## DUT Serial Console Log (preprocessed)\n")
        text = preprocess_log(serial_log, max_bytes=150_000)
        # Focus on failures if any
        if "FAIL" in text or "panic" in text.lower():
            text = extract_failure_window(text, "FAIL", before=100, after=30)
        parts.append("```\n" + text + "\n```\n")

    # iperf3 JSON results
    for f in sorted(run_dir.glob("iperf_*.json")):
        parts.append(f"## {f.name}\n")
        parts.append("```json\n" + f.read_text()[:5_000] + "\n```\n")

    # Any other *.log file
    for f in sorted(run_dir.glob("*.log")):
        if f.name == "dut_serial.log":
            continue
        parts.append(f"## {f.name}\n")
        text = preprocess_log(f, max_bytes=50_000)
        parts.append("```\n" + text + "\n```\n")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Render Markdown report
# ---------------------------------------------------------------------------
def render_markdown(report: dict) -> str:
    lines = [
        f"# Test Report — {report.get('test_case', 'unknown')}",
        "",
        f"**Status:** {report.get('status', '?')}  ",
        f"**Severity:** {report.get('severity', '?')}  ",
        f"**Confidence:** {report.get('confidence', '?')}  ",
        f"**Category:** {report.get('category', '?')}  ",
        "",
        "## Root Cause",
        "",
        report.get("root_cause", "(empty)") or "(empty)",
        "",
        "## Evidence",
        "",
    ]
    for item in report.get("evidence", []):
        lines.append(f"- `{item}`")
    lines += [
        "",
        "## Suggested Action",
        "",
        report.get("suggested_action", "(none)") or "(none)",
        "",
        "## Related Components",
        "",
        ", ".join(report.get("related_components", [])) or "(none)",
        "",
    ]
    if hint := report.get("regression_hint"):
        lines += ["## Regression Hint", "", hint, ""]
    return "\n".join(lines)


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
    ap.add_argument("--prompt", default=None,
                    help="Override prompt file path")
    ap.add_argument("--model", default=None)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the payload that WOULD be sent; do not call API")
    args = ap.parse_args()

    run_dir = resolve_run_dir(args.run_dir)
    print(f"[+] Analyzing {run_dir}")

    cfg = yaml.safe_load(open(args.config)) if Path(args.config).exists() else {}
    claude_cfg = cfg.get("claude", {})
    prompt_path = args.prompt or claude_cfg.get("prompt_template", "prompts/wifi_triage.md")
    model = args.model or claude_cfg.get("model", "claude-opus-4-7")
    max_tokens = claude_cfg.get("max_tokens", 4000)

    system_prompt = Path(prompt_path).read_text()
    user_payload = build_user_payload(run_dir)

    print(f"[+] Payload size: {len(user_payload):,} chars")

    if args.dry_run:
        print("\n" + "=" * 70)
        print(user_payload[:5000])
        print("... (truncated)" if len(user_payload) > 5000 else "")
        return

    print(f"[+] Calling Claude ({model})...")
    response_text = call_claude(system_prompt, user_payload,
                                 model=model, max_tokens=max_tokens)

    # Try to parse as JSON (stripping any stray fences just in case)
    cleaned = response_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()

    try:
        report = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"[!] Failed to parse Claude response as JSON: {e}")
        (run_dir / "claude_raw.txt").write_text(response_text)
        sys.exit(1)

    # Write outputs
    (run_dir / "claude_report.json").write_text(json.dumps(report, indent=2))
    (run_dir / "claude_report.md").write_text(render_markdown(report))

    print(f"[+] Wrote {run_dir}/claude_report.json")
    print(f"[+] Wrote {run_dir}/claude_report.md")
    print()
    print(f"  Status:    {report.get('status')}")
    print(f"  Severity:  {report.get('severity')}")
    print(f"  Cause:     {report.get('root_cause', '')[:80]}")


if __name__ == "__main__":
    main()
