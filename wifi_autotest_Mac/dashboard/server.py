#!/usr/bin/env python3
"""
dashboard/server.py
-------------------
WiFi-ATS Dashboard backend (FastAPI).

Usage:
    cd wifi_autotest_Mac/dashboard
    uvicorn server:app --reload --port 8080
    # open http://localhost:8080
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import platform
import re
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
DASHBOARD_DIR = Path(__file__).parent
PROJECT_ROOT  = DASHBOARD_DIR.parent          # wifi_autotest_Mac/
RUNS_DIR      = PROJECT_ROOT / "runs"
RUN_BG        = PROJECT_ROOT / "run_bg.sh"
STATE_FILE    = Path("/tmp/wifi_ats_state.json")  # {pid, log_file, mode}

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(title="WiFi-ATS Dashboard", docs_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _parse_junit(run_dir: Path) -> dict:
    junit = run_dir / "junit.xml"
    if not junit.exists():
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "cases": []}
    try:
        root = ET.parse(junit).getroot()
        suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
        total    = sum(int(s.get("tests",    0)) for s in suites)
        failures = sum(int(s.get("failures", 0)) for s in suites)
        errors   = sum(int(s.get("errors",   0)) for s in suites)
        cases = []
        for suite in suites:
            for tc in suite.findall("testcase"):
                status, message = "passed", ""
                if tc.find("failure") is not None:
                    status  = "failed"
                    message = (tc.find("failure").get("message") or "")[:300]
                elif tc.find("error") is not None:
                    status  = "error"
                    message = (tc.find("error").get("message") or "")[:300]
                cases.append({
                    "name":      tc.get("name", ""),
                    "classname": tc.get("classname", ""),
                    "time":      float(tc.get("time", 0)),
                    "status":    status,
                    "message":   message,
                })
        return {"total": total, "passed": total - failures - errors,
                "failed": failures, "errors": errors, "cases": cases}
    except Exception:
        return {"total": 0, "passed": 0, "failed": 0, "errors": 0, "cases": []}


def _run_info(run_dir: Path) -> dict:
    name = run_dir.name
    is_stability = name.startswith("stability-")
    ts = name.replace("stability-", "")

    info: dict = {"id": name, "timestamp": ts,
                  "type": "stability" if is_stability else "rf"}

    if is_stability:
        info.update({"total": 0, "passed": 0, "failed": 0})
        data_file = run_dir / "stability_data.json"
        if data_file.exists():
            try:
                d = json.loads(data_file.read_text())
                s = d.get("summary", {})
                info["stability"] = {
                    "band":        s.get("band", "?"),
                    "checks":      s.get("checks", 0),
                    "drops":       s.get("wifi_disconnects", 0),
                    "dl_avg_mbps": s.get("dl_avg_mbps", 0),
                    "ul_avg_mbps": s.get("ul_avg_mbps", 0),
                    "duration_s":  s.get("duration_s", 0),
                    "result":      "PASS" if s.get("wifi_disconnects", 0) == 0
                                            and s.get("iperf_failures", 0) == 0
                                            and s.get("anomaly_count", 0) == 0
                                   else "FAIL",
                }
            except Exception:
                pass
    else:
        j = _parse_junit(run_dir)
        info.update({"total": j["total"], "passed": j["passed"],
                     "failed": j["failed"], "errors": j["errors"]})

    info["has_ai_report"] = (run_dir / "claude_report.md").exists()
    info["has_summary"]   = (run_dir / "summary_report.html").exists()
    return info


def _read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state))


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
@app.get("/api/runs")
def list_runs():
    if not RUNS_DIR.exists():
        return []
    runs = []
    for d in sorted(RUNS_DIR.iterdir(), reverse=True):
        if d.is_dir() and not d.name.startswith("bg_") and not d.name.startswith("diag_"):
            try:
                runs.append(_run_info(d))
            except Exception:
                pass
    return runs[:60]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    run_dir = RUNS_DIR / run_id
    if not run_dir.is_dir():
        raise HTTPException(404, "Run not found")
    info = _run_info(run_dir)

    if info["type"] != "stability":
        info["cases"] = _parse_junit(run_dir)["cases"]

    ai = run_dir / "claude_report.md"
    if ai.exists():
        info["ai_report"] = ai.read_text(errors="replace")

    stability_data = run_dir / "stability_data.json"
    if stability_data.exists():
        try:
            info["stability_data"] = json.loads(stability_data.read_text())
        except Exception:
            pass

    return info


class TriggerReq(BaseModel):
    mode: str = "rf"   # "rf" | "stability" | "rf stability"


@app.post("/api/trigger")
def trigger(req: TriggerReq):
    state = _read_state()
    if state.get("pid") and _is_running(state["pid"]):
        return {"status": "already_running", "pid": state["pid"]}

    if not RUN_BG.exists():
        raise HTTPException(500, f"run_bg.sh not found at {RUN_BG}")

    args = req.mode.split()
    proc = subprocess.run(
        ["bash", str(RUN_BG)] + args,
        cwd=str(PROJECT_ROOT),
        capture_output=True, text=True,
    )
    stdout = proc.stdout

    pid_match  = re.search(r"PID\s+(\d+)\s+started", stdout)
    log_match  = re.search(r"Log\s*:\s*(\S+)", stdout)
    pid      = int(pid_match.group(1))  if pid_match  else 0
    log_file = str(PROJECT_ROOT / log_match.group(1)) if log_match else ""

    _write_state({"pid": pid, "log_file": log_file, "mode": req.mode})
    return {"status": "started", "pid": pid, "log_file": log_file}


@app.get("/api/status")
def get_status():
    state = _read_state()
    pid = state.get("pid", 0)
    if pid and _is_running(pid):
        return {"running": True, "pid": pid,
                "mode": state.get("mode"), "log_file": state.get("log_file")}
    return {"running": False}


@app.delete("/api/trigger")
def stop_test():
    state = _read_state()
    pid = state.get("pid", 0)
    if not pid:
        return {"status": "not_running"}
    try:
        os.kill(pid, 15)
        STATE_FILE.unlink(missing_ok=True)
        return {"status": "stopped", "pid": pid}
    except OSError:
        STATE_FILE.unlink(missing_ok=True)
        return {"status": "already_stopped"}


@app.get("/api/log/stream")
async def stream_log():
    state = _read_state()
    log_file = state.get("log_file", "")

    # Fallback: latest bg_*.log
    if not log_file or not Path(log_file).exists():
        bg_logs = sorted(RUNS_DIR.glob("bg_*.log"), reverse=True)
        log_file = str(bg_logs[0]) if bg_logs else ""

    async def generate():
        if not log_file or not Path(log_file).exists():
            yield "data: (no log file found)\n\n"
            return
        with open(log_file, errors="replace") as f:
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                else:
                    status = get_status()
                    if not status["running"]:
                        yield "data: [DONE]\n\n"
                        return
                    await asyncio.sleep(0.4)

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# Station status
# ---------------------------------------------------------------------------
def _ping(ip: str) -> bool:
    try:
        flag = "-t" if platform.system() == "Darwin" else "-W"
        r = subprocess.run(
            ["ping", "-c", "1", flag, "2", ip],
            capture_output=True, timeout=5,
        )
        return r.returncode == 0
    except Exception:
        return False


def _check_pkg(pkg: str) -> bool:
    try:
        __import__(pkg)
        return True
    except ImportError:
        return False


def _check_iperf3() -> bool:
    try:
        r = subprocess.run(["iperf3", "--version"], capture_output=True, timeout=2)
        return r.returncode == 0
    except Exception:
        return False


def _read_env_key() -> tuple[bool, str]:
    env_file = PROJECT_ROOT / ".env"
    val = os.environ.get("ANTHROPIC_API_KEY", "")
    if not val and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                val = line.split("=", 1)[1].strip().strip("'\"")
    if val:
        preview = val[:12] + "..." + val[-4:] if len(val) > 16 else "***"
        return True, preview
    return False, ""


@app.get("/api/station/status")
async def station_status():
    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor() as ex:
        dut_f = loop.run_in_executor(ex, _ping, "192.168.99.1")
        bpi_f = loop.run_in_executor(ex, _ping, "192.168.99.100")
        dut_ok, bpi_ok = await asyncio.gather(dut_f, bpi_f)

    api_set, api_preview = _read_env_key()

    packages = {
        "pytest":    _check_pkg("pytest"),
        "paramiko":  _check_pkg("paramiko"),
        "anthropic": _check_pkg("anthropic"),
        "fastapi":   _check_pkg("fastapi"),
        "uvicorn":   _check_pkg("uvicorn"),
        "iperf3":    _check_iperf3(),
    }

    return {
        "nodes": {
            "dut": {"ip": "192.168.99.1",   "ok": dut_ok},
            "bpi": {"ip": "192.168.99.100", "ok": bpi_ok},
        },
        "api_key":  {"set": api_set, "preview": api_preview},
        "packages": packages,
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.get("/api/settings")
def get_settings():
    api_set, api_preview = _read_env_key()

    dut_ip, bpi_ip = "192.168.99.1", "192.168.99.100"
    config_file = PROJECT_ROOT / "config.yaml"
    if config_file.exists():
        try:
            import yaml
            with open(config_file) as f:
                cfg = yaml.safe_load(f) or {}
            dut_ip = cfg.get("dut", {}).get("host", dut_ip)
            bpi_ip = cfg.get("bpi", {}).get("host", bpi_ip)
        except Exception:
            pass

    return {
        "api_key_set":     api_set,
        "api_key_preview": api_preview,
        "dut_ip":          dut_ip,
        "bpi_ip":          bpi_ip,
    }


class SettingsReq(BaseModel):
    api_key: Optional[str] = None


@app.post("/api/settings")
def save_settings(req: SettingsReq):
    if req.api_key is not None:
        env_file = PROJECT_ROOT / ".env"
        lines = env_file.read_text().splitlines() if env_file.exists() else []
        found = False
        for i, line in enumerate(lines):
            if line.startswith("ANTHROPIC_API_KEY="):
                lines[i] = f"ANTHROPIC_API_KEY={req.api_key}"
                found = True
        if not found:
            lines.append(f"ANTHROPIC_API_KEY={req.api_key}")
        env_file.write_text("\n".join(lines) + "\n")
    return {"status": "saved"}


# Static files — mount last so API routes take priority
app.mount("/", StaticFiles(directory=str(DASHBOARD_DIR / "static"), html=True))
