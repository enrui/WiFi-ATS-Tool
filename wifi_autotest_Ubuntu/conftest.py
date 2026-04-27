"""
conftest.py
-----------
Shared pytest fixtures.
  - `cfg`         : loaded config.yaml
  - `run_dir`     : per-session directory for logs (./runs/YYYYMMDD-HHMMSS/)
  - `dut_ssh`     : SSH connection to DUT (session-scoped)
  - `bpi_ssh`     : SSH connection to BPI-R4 (session-scoped)
  - `dut_serial`  : Serial console to DUT (session-scoped, always capturing)
"""
from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path

import pytest

# Make `lib` importable
sys.path.insert(0, str(Path(__file__).parent))
from lib.devices import (  # noqa: E402
    Config, make_dut_ssh, make_bpi_ssh, make_dut_serial
)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def cfg() -> Config:
    path = os.environ.get("WIFI_AUTOTEST_CONFIG", "config.yaml")
    if not Path(path).exists():
        pytest.exit(
            f"Config file '{path}' not found. "
            "Copy config.yaml.example to config.yaml and fill it in."
        )
    return Config.load(path)


@pytest.fixture(scope="session")
def run_dir(cfg) -> Path:
    # run_all.sh sets WIFI_AUTOTEST_RUN_DIR so iperf JSONs land in the same
    # directory as junit.xml and device logs.  Falls back to a timestamped dir
    # when pytest is invoked directly (e.g. during development).
    env_dir = os.environ.get("WIFI_AUTOTEST_RUN_DIR")
    if env_dir:
        d = Path(env_dir)
    else:
        base = Path(cfg.get("controller.log_dir", "./runs"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        d = base / stamp
    d.mkdir(parents=True, exist_ok=True)
    logging.info(f"Run directory: {d.resolve()}")
    return d


@pytest.fixture(scope="session")
def dut_ssh(cfg):
    dev = make_dut_ssh(cfg)
    try:
        dev.connect()
    except Exception as e:
        pytest.exit(f"Could not SSH to DUT: {e}")
    yield dev
    dev.close()


@pytest.fixture(scope="session")
def bpi_ssh(cfg):
    dev = make_bpi_ssh(cfg)
    try:
        dev.connect()
    except Exception as e:
        pytest.exit(f"Could not SSH to BPI-R4: {e}")
    yield dev
    dev.close()


@pytest.fixture(scope="session")
def dut_serial(cfg, run_dir):
    log_path = run_dir / "dut_serial.log"
    ser = make_dut_serial(cfg, log_path=str(log_path))
    try:
        ser.open()
    except Exception as e:
        pytest.exit(f"Could not open serial port: {e}")
    yield ser
    ser.close()


# ---------------------------------------------------------------------------
# Per-test logging hook
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _test_banner(request, run_dir):
    """Print a visible banner at the start/end of each test, saved to run log."""
    name = request.node.nodeid
    logging.info(f"{'='*70}")
    logging.info(f"BEGIN  {name}")
    logging.info(f"{'='*70}")
    start = time.time()
    yield
    elapsed = time.time() - start
    outcome = "PASS" if not hasattr(request.node, "rep_call") or \
              request.node.rep_call.passed else "FAIL"
    logging.info(f"END    {name}  [{outcome}]  ({elapsed:.1f}s)")


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
