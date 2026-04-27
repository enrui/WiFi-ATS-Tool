"""
lib/logtools.py
---------------
Log preprocessing utilities:
  - Redact sensitive info (MAC, S/N) before sending to Claude
  - Filter noise (repeated lines, boot banners)
  - Split logs by test-case boundary
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# Redaction patterns
# ---------------------------------------------------------------------------
MAC_RE = re.compile(r"\b([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b")
SN_RE  = re.compile(r"\b(S/N|Serial)[\s:]+([A-Z0-9]{6,})\b", re.IGNORECASE)
API_KEY_RE = re.compile(r"\b(sk-ant-[a-zA-Z0-9_-]{20,}|api[_-]?key[\"'\s:=]+[a-zA-Z0-9_-]{16,})\b", re.IGNORECASE)

# Lines that appear 100s of times and add no signal
NOISE_PATTERNS = [
    re.compile(r"^\s*$"),                           # blank lines
    re.compile(r"watchdog: BUG: soft lockup"),       # too verbose
    re.compile(r"^\[\s*\d+\.\d+\]\s+random:"),       # random pool messages
]


def redact(text: str) -> str:
    """Remove sensitive identifiers from log text."""
    text = MAC_RE.sub("[MAC]", text)
    text = SN_RE.sub(r"\1: [SN]", text)
    text = API_KEY_RE.sub("[REDACTED_KEY]", text)
    return text


def filter_noise(lines: Iterable[str]) -> list[str]:
    """Drop blank lines and repeat-heavy debug noise."""
    out = []
    prev = None
    repeat = 0
    for line in lines:
        if any(p.search(line) for p in NOISE_PATTERNS):
            continue
        if line == prev:
            repeat += 1
            if repeat < 3:
                out.append(line)
            elif repeat == 3:
                out.append("    ... (repeated) ...")
            continue
        repeat = 0
        prev = line
        out.append(line)
    return out


def preprocess_log(path: str | Path, max_bytes: int = 500_000) -> str:
    """
    Read a log file, redact, filter, and truncate to a Claude-friendly size.
    Keeps the TAIL of the log (most recent events usually matter most).
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    text = redact(text)
    lines = text.splitlines()
    lines = filter_noise(lines)
    joined = "\n".join(lines)
    if len(joined) > max_bytes:
        # Keep tail + short head so Claude has context of the beginning too
        head = joined[:50_000]
        tail = joined[-(max_bytes - 50_000):]
        joined = head + "\n\n... [truncated middle] ...\n\n" + tail
    return joined


def extract_failure_window(text: str, marker: str = "FAIL", before: int = 200, after: int = 50) -> str:
    """
    Around each occurrence of `marker`, extract a window of lines.
    Useful for zooming in on crashes or assertion failures.
    """
    lines = text.splitlines()
    hits = [i for i, l in enumerate(lines) if marker in l]
    if not hits:
        return text[-20_000:]  # no marker, return tail
    windows = []
    for idx in hits:
        start = max(0, idx - before)
        end = min(len(lines), idx + after)
        windows.append("\n".join(lines[start:end]))
        windows.append("---")
    return "\n".join(windows)
