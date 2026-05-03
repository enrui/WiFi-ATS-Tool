#!/usr/bin/env python3
"""
claude_api_analyze.py
---------------------
Call Anthropic API to analyze a WiFi test failure and write claude_report.md.
Replaces the `claude --print` call in run_all.sh.

Requires: ANTHROPIC_API_KEY environment variable

Usage:
    python tools/claude_api_analyze.py <run_dir>
    python tools/claude_api_analyze.py runs/20260427-120000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import anthropic

SYSTEM_PROMPT = (
    "You are a WiFi router test automation expert. "
    "Analyze test failures concisely and provide actionable root-cause analysis. "
    "Respond in Markdown."
)

MODEL = "claude-sonnet-4-6"
MAX_OUTPUT_TOKENS = 2048

# Token budget per section (rough chars / 4 ≈ tokens)
_LIMIT_JUNIT     = 8_000   # chars
_LIMIT_DIAG      = 40_000  # chars  (live_diagnostics.json can be large)
_LIMIT_STDOUT    = 12_000  # chars  (keep tail — most recent = most relevant)


def _read_tail(path: Path, max_chars: int) -> str:
    text = path.read_text(errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text


def _read_head(path: Path, max_chars: int) -> str:
    text = path.read_text(errors="replace")
    return text[:max_chars] if len(text) > max_chars else text


def build_prompt(run_dir: Path) -> str:
    sections: list[str] = []

    junit = run_dir / "junit.xml"
    if junit.exists():
        sections.append(
            "## Test Results (junit.xml)\n```xml\n"
            + _read_head(junit, _LIMIT_JUNIT)
            + "\n```"
        )

    diag = run_dir / "live_diagnostics.json"
    if diag.exists():
        sections.append(
            "## Live Diagnostics (live_diagnostics.json)\n```json\n"
            + _read_head(diag, _LIMIT_DIAG)
            + "\n```"
        )

    stdout = run_dir / "pytest_stdout.log"
    if stdout.exists():
        sections.append(
            "## pytest Output (last portion)\n```\n"
            + _read_tail(stdout, _LIMIT_STDOUT)
            + "\n```"
        )

    body = "\n\n".join(sections)
    body += """

## Your Task

Write a Markdown failure analysis report with these sections:

### 1. Failed Tests
List each failed test with its exact assertion error.

### 2. Root Cause
Based on the diagnostic data (iw dev, dmesg, wpa_supplicant state, iperf logs).

### 3. Key Evidence
Quote specific lines from the diagnostics that support the root cause.

### 4. Suggested Fix
Concrete, actionable steps. If a DUT config change is needed, state exactly what \
to change — do NOT apply it automatically.
"""
    return body


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python tools/claude_api_analyze.py <run_dir>", file=sys.stderr)
        sys.exit(1)

    run_dir = Path(sys.argv[1])
    if not run_dir.is_dir():
        print(f"[!] Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(1)

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("[!] ANTHROPIC_API_KEY is not set — skipping AI analysis.", file=sys.stderr)
        sys.exit(1)

    print(f"[+] Building analysis prompt from {run_dir} ...")
    prompt = build_prompt(run_dir)
    print(f"[+] Prompt size: ~{len(prompt) // 4} tokens (estimated)")

    print(f"[+] Calling Anthropic API ({MODEL}) ...")
    client = anthropic.Anthropic(api_key=api_key)

    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    usage = response.usage
    print(f"[+] Tokens used — input: {usage.input_tokens}, output: {usage.output_tokens}")

    report = response.content[0].text
    out = run_dir / "claude_report.md"
    out.write_text(report)
    print(f"[+] Report written → {out}")


if __name__ == "__main__":
    main()
