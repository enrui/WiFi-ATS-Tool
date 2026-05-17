#!/usr/bin/env python3
"""
Router Reset Stress Test
流程：
  1. 開啟瀏覽器 → 連到 <web_host>/login.html，以 web_user/web_password 登入
  2. 確認跳轉到 wizard.html（表示 DUT 已回到出廠狀態）
  3. 透過 serial console 執行 /opt/bin/restore_to_default.sh
  4. 監控 serial 等待 DUT 重開機完成，記錄 boot time
  5. 重複 N 輪（N=0 表示無限循環）
  6. 結束後將彙整結果寫入 runs/reset-<timestamp>/result.json

Usage:
  python3 scripts/reset_test.py                 # read config.yaml, infinite loop
  python3 scripts/reset_test.py --iterations 5  # run 5 times then exit
  python3 scripts/reset_test.py --config /path/to/config.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# ── Locate project root (this file lives in <root>/scripts/) ─────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR     = PROJECT_ROOT / "runs"

# ── Defaults (overridden by config.yaml) ─────────────────────────────────────
ROUTER_IP    = "192.168.1.1"
WEB_USER     = "admin"
WEB_PASSWORD = "admin"
SERIAL_PORT  = "/dev/tty.usbserial-0001"
BAUD_RATE    = 115200
RESTORE_CMD  = "/opt/bin/restore_to_default.sh"

WAIT_SECS           = 4 * 60
LOGIN_TIMEOUT_MS    = 30_000
BOOT_TIME_WARN_SECS = 4 * 60
BOOT_DETECT_PATTERNS = [
    b"Please press Enter to activate this console",
    b"BusyBox v",
    b"OpenWrt",
    b"# ",
    b"login:",
]


def _load_config(config_path: Path) -> dict:
    global ROUTER_IP, WEB_USER, WEB_PASSWORD, SERIAL_PORT, BAUD_RATE
    if not config_path.exists():
        return {}
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        dut = cfg.get("dut", {})
        ROUTER_IP    = dut.get("web_host",     ROUTER_IP)
        WEB_USER     = dut.get("web_user",     WEB_USER)
        WEB_PASSWORD = dut.get("web_password", WEB_PASSWORD)
        SERIAL_PORT  = dut.get("serial_port",  SERIAL_PORT)
        BAUD_RATE    = int(dut.get("serial_baud", BAUD_RATE))
        return cfg
    except Exception as e:
        print(f"[WARN] Failed to load config: {e}", flush=True)
        return {}


# ── Logging ───────────────────────────────────────────────────────────────────
_log_file: Path | None = None

def log(msg: str, level: str = "INFO") -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:5s}] {msg}"
    print(line, flush=True)
    if _log_file:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ── Browser step ──────────────────────────────────────────────────────────────
def browser_login() -> bool:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        log("playwright not installed — skipping browser step", "WARN")
        return True

    login_url = f"http://{ROUTER_IP}/login.html"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_context().new_page()
        try:
            log(f"Browser: 開啟 {login_url}")
            page.goto(login_url, timeout=LOGIN_TIMEOUT_MS)

            page.locator(
                "input[name='Username'], input[name='username'], "
                "input[id='username'], input[id='user'], input[type='text']"
            ).first.fill(WEB_USER)

            page.locator("input[type='password']").first.fill(WEB_PASSWORD)

            page.locator(
                "button[type='submit'], input[type='submit'], "
                "button:has-text('Login'), button:has-text('登入'), "
                "a:has-text('Login')"
            ).first.click()

            page.wait_for_url("**/wizard.html", timeout=LOGIN_TIMEOUT_MS)
            log(f"Browser: 登入成功 → {page.url}")
            return True

        except PwTimeout:
            log(f"Browser: 逾時，URL={page.url}", "WARN")
            return False
        except Exception as e:
            log(f"Browser: 例外 — {e}", "ERROR")
            return False
        finally:
            browser.close()


# ── Serial restore ────────────────────────────────────────────────────────────
def serial_restore() -> tuple[bool, float]:
    try:
        import serial
    except ImportError:
        log("pyserial not installed — cannot perform restore", "ERROR")
        return False, 0.0

    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5) as ser:
            log(f"Serial: 開啟 {SERIAL_PORT} @ {BAUD_RATE} baud")
            time.sleep(0.5)
            ser.write(b"\r\n")
            time.sleep(1.5)
            ser.reset_input_buffer()

            ser.write(f"{RESTORE_CMD}\r\n".encode())
            t_restore = time.time()
            log(f"Serial: 執行 → {RESTORE_CMD}")

            time.sleep(3)
            out = ser.read(ser.in_waiting).decode(errors="replace").strip()
            if out:
                log(f"Serial output: {out[:400]}")
            return True, t_restore

    except Exception as e:
        log(f"Serial: 錯誤 — {e}", "ERROR")
        return False, 0.0


# ── Boot monitor ──────────────────────────────────────────────────────────────
def monitor_serial_boot(iteration: int, secs: int, t_restore: float,
                        serial_log_dir: Path) -> tuple[str, bool, float]:
    serial_log = str(serial_log_dir / f"serial_boot_iter{iteration:04d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
    log(f"Serial monitor: 開始記錄重開機輸出 → {serial_log}")

    try:
        import serial as _serial
    except ImportError:
        log("pyserial not installed — skipping boot monitor", "WARN")
        return serial_log, False, 0.0

    end          = time.time() + secs
    boot_detected = False
    boot_time_s   = 0.0
    bytes_cap     = 0
    buf           = b""

    time.sleep(2)
    try:
        with _serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            with open(serial_log, "wb") as sf:
                while time.time() < end:
                    remaining = int(end - time.time())
                    mm, ss = divmod(remaining, 60)
                    status = f"boot:{boot_time_s:.0f}s ✓" if boot_detected else "等待開機…"
                    print(f"\r  {status}  剩餘 {mm:02d}:{ss:02d}  [serial: {bytes_cap} bytes]  ",
                          end="", flush=True)

                    chunk = ser.read(ser.in_waiting or 1)
                    if chunk:
                        sf.write(chunk); sf.flush()
                        bytes_cap += len(chunk)
                        if not boot_detected:
                            buf = (buf + chunk)[-512:]
                            for pat in BOOT_DETECT_PATTERNS:
                                if pat in buf:
                                    boot_time_s   = time.time() - t_restore
                                    boot_detected = True
                                    log(f"\nSerial: 開機完成 pattern={pat.decode(errors='replace').strip()!r}"
                                        f"  boot time={boot_time_s:.1f}s")
                                    if boot_time_s > BOOT_TIME_WARN_SECS:
                                        log(f"Serial: ⚠ boot time {boot_time_s:.0f}s 超過門檻", "WARN")
                                    break
    except Exception as e:
        print()
        log(f"Serial monitor: 無法開啟 port — {e}", "WARN")

    print()
    if not boot_detected:
        log(f"Serial monitor: ⚠ {secs}s 內未偵測到開機完成", "WARN")
    log(f"Serial monitor: 完成，共捕捉 {bytes_cap} bytes")
    return serial_log, boot_detected, boot_time_s


# ── Result writer ─────────────────────────────────────────────────────────────
def _write_result(run_dir: Path, iterations: list[dict],
                  success: int, failure: int) -> None:
    result = {
        "type":      "reset",
        "total":     success + failure,
        "success":   success,
        "failure":   failure,
        "result":    "PASS" if failure == 0 else "FAIL",
        "iterations": iterations,
    }
    (run_dir / "result.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    global _log_file

    parser = argparse.ArgumentParser(description="Router Reset Stress Test")
    parser.add_argument("--iterations", type=int, default=0,
                        help="Number of reset cycles (0 = infinite)")
    parser.add_argument("--config", type=Path,
                        default=PROJECT_ROOT / "config.yaml")
    args = parser.parse_args()

    _load_config(args.config)

    # Create run directory
    stamp   = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / f"reset-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _log_file = run_dir / "reset_test.log"

    log(f"=== Router Reset Stress Test  iterations={'∞' if args.iterations == 0 else args.iterations} ===")
    log(f"    Web: http://{ROUTER_IP}  user={WEB_USER}")
    log(f"    Serial: {SERIAL_PORT} @ {BAUD_RATE}")
    log(f"    Run dir: {run_dir}")

    success_count = 0
    failure_count = 0
    iteration_log: list[dict] = []
    iteration      = 0

    def _on_signal(sig, frame):
        log(f"=== 中斷  成功:{success_count}  失敗:{failure_count} ===")
        _write_result(run_dir, iteration_log, success_count, failure_count)
        sys.exit(0)

    signal.signal(signal.SIGINT,  _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    while True:
        iteration += 1
        if args.iterations > 0 and iteration > args.iterations:
            break

        log(f"{'─'*55}")
        log(f"第 {iteration} 輪  (✓{success_count}  ✗{failure_count})")
        iter_info: dict = {"iteration": iteration, "result": "FAIL",
                           "browser_ok": False, "serial_ok": False,
                           "boot_detected": False, "boot_time_s": 0.0}
        ok = True

        # Step 1 — browser login
        if not browser_login():
            ok = False
            log("Step 1 FAIL: 無法確認 wizard.html", "WARN")
        else:
            iter_info["browser_ok"] = True

        # Step 2 — serial restore
        t_restore = 0.0
        if ok:
            restore_ok, t_restore = serial_restore()
            if not restore_ok:
                ok = False
                log("Step 2 FAIL: serial restore 失敗", "WARN")
            else:
                iter_info["serial_ok"] = True

        # Step 3 — monitor boot
        log(f"等待 {WAIT_SECS//60} 分鐘，監控重開機過程…")
        serial_log_path, boot_detected, boot_time_s = monitor_serial_boot(
            iteration, WAIT_SECS, t_restore, run_dir)
        iter_info["boot_detected"] = boot_detected
        iter_info["boot_time_s"]   = round(boot_time_s, 1)

        if ok and not boot_detected:
            ok = False
            log("Step 3 FAIL: 未偵測到裝置開機完成", "WARN")

        if ok:
            success_count += 1
            iter_info["result"] = "PASS"
            log(f"第 {iteration} 輪 ✓ PASS  累計 ✓{success_count} ✗{failure_count}")
            # Remove serial log on pass — only keep on fail
            serial_log_file = Path(serial_log_path)
            if serial_log_file.exists():
                serial_log_file.unlink()
        else:
            failure_count += 1
            iter_info["serial_log"] = serial_log_path
            log(f"第 {iteration} 輪 ✗ FAIL  累計 ✓{success_count} ✗{failure_count}  → {serial_log_path}", "WARN")

        iteration_log.append(iter_info)
        _write_result(run_dir, iteration_log, success_count, failure_count)

    log(f"=== 完成  成功:{success_count}  失敗:{failure_count} ===")
    _write_result(run_dir, iteration_log, success_count, failure_count)


if __name__ == "__main__":
    main()
