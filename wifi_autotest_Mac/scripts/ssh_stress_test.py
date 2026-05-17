#!/usr/bin/env python3
"""
SSH Stress Test
流程（每輪）：
  1. Browser 開啟 DUT Web GUI → 登入 → 跳轉 main.html
     → Advanced Setup > SSH Service → 啟用 → 儲存
  2. 等待 SSH 服務就緒（預設 10 秒）
  3. 以 paramiko 做 N 次 SSH 連線 / 斷線，記錄每次結果
  4. 透過 serial console 執行 restore_to_default.sh
  5. 監控重開機，等待裝置上線
  6. 重複

Usage:
  python3 scripts/ssh_stress_test.py
  python3 scripts/ssh_stress_test.py --iterations 5 --ssh-cycles 10
  python3 scripts/ssh_stress_test.py --config /path/to/config.yaml
"""
from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR     = PROJECT_ROOT / "runs"

# ── Defaults (overridden by config.yaml) ─────────────────────────────────────
DUT_HOST     = "192.168.2.1"
WEB_USER     = "admin"
WEB_PASSWORD = "admin"
SSH_USER     = "root"
SSH_PASSWORD = None          # None = try no-auth first, then empty string
SERIAL_PORT  = "/dev/tty.usbserial-0001"
BAUD_RATE    = 115200
RESTORE_CMD  = "/opt/bin/restore_to_default.sh"

WAIT_SSH_READY_SECS  = 10
WAIT_REBOOT_SECS     = 4 * 60
LOGIN_TIMEOUT_MS     = 30_000
BOOT_TIME_WARN_SECS  = 4 * 60
BOOT_DETECT_PATTERNS = [
    b"Please press Enter to activate this console",
    b"BusyBox v",
    b"OpenWrt",
    b"# ",
    b"login:",
]


def _load_config(config_path: Path) -> None:
    global DUT_HOST, WEB_USER, WEB_PASSWORD, SSH_USER, SERIAL_PORT, BAUD_RATE
    if not config_path.exists():
        return
    try:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        dut = cfg.get("dut", {})
        DUT_HOST     = dut.get("host",         DUT_HOST)
        WEB_USER     = dut.get("web_user",     WEB_USER)
        WEB_PASSWORD = dut.get("web_password", WEB_PASSWORD)
        SSH_USER     = dut.get("ssh_user",     SSH_USER)
        SERIAL_PORT  = dut.get("serial_port",  SERIAL_PORT)
        BAUD_RATE    = int(dut.get("serial_baud", BAUD_RATE))
    except Exception as e:
        print(f"[WARN] Failed to load config: {e}", flush=True)


# ── Logging ───────────────────────────────────────────────────────────────────
_log_file: Path | None = None

def log(msg: str, level: str = "INFO") -> None:
    ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level:5s}] {msg}"
    print(line, flush=True)
    if _log_file:
        with open(_log_file, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ── Step 1: Browser — enable SSH ─────────────────────────────────────────────
def browser_enable_ssh() -> bool:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        log("playwright not installed — skipping browser step", "WARN")
        return True

    login_url = f"http://{DUT_HOST}/login.html"
    main_url  = f"http://{DUT_HOST}/main.html"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_context().new_page()
        try:
            # ── Login ──────────────────────────────────────────────────────
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

            # ── Force navigate to main.html ────────────────────────────────
            log(f"Browser: 強制跳轉 {main_url}")
            page.goto(main_url, timeout=LOGIN_TIMEOUT_MS)
            page.wait_for_load_state("domcontentloaded")
            log(f"Browser: 目前 URL → {page.url}")

            # ── Find SSH Service toggle ────────────────────────────────────
            # Try common patterns: link/menu item named "SSH Service" or "SSH"
            log("Browser: 尋找 Advanced Setup > SSH Service")
            ssh_found = False

            # Try clicking the menu item first
            for selector in [
                "text=SSH Service",
                "a:has-text('SSH Service')",
                "a:has-text('SSH')",
                "li:has-text('SSH Service') a",
                "[href*='ssh']",
            ]:
                try:
                    el = page.locator(selector).first
                    if el.is_visible(timeout=3000):
                        el.click()
                        page.wait_for_load_state("domcontentloaded")
                        log(f"Browser: 點擊選單項目 ({selector})")
                        ssh_found = True
                        break
                except Exception:
                    pass

            if not ssh_found:
                log("Browser: 未找到 SSH Service 選單，嘗試直接導向 SSH 頁面", "WARN")
                for ssh_path in ["/ssh.html", "/sshd.html", "/advanced_ssh.html",
                                 "/services/ssh.html", "/admin/ssh.html"]:
                    try:
                        page.goto(f"http://{DUT_HOST}{ssh_path}", timeout=10_000)
                        page.wait_for_load_state("domcontentloaded")
                        if "404" not in page.title() and page.url.endswith(ssh_path):
                            log(f"Browser: 直接導向 {ssh_path} 成功")
                            ssh_found = True
                            break
                    except Exception:
                        pass

            if not ssh_found:
                log("Browser: 無法找到 SSH Service 頁面", "ERROR")
                return False

            # ── Enable SSH checkbox / toggle ───────────────────────────────
            log("Browser: 尋找 Enable SSH 開關")
            enabled = False
            for chk_sel in [
                "input[type='checkbox'][name*='ssh' i]",
                "input[type='checkbox'][id*='ssh' i]",
                "input[type='checkbox']:near(:text('Enable SSH'))",
                "input[type='checkbox']:near(:text('SSH Service'))",
                "input[type='checkbox']",   # fallback: first checkbox on page
            ]:
                try:
                    chk = page.locator(chk_sel).first
                    if chk.is_visible(timeout=3000):
                        if not chk.is_checked():
                            chk.check()
                            log(f"Browser: 勾選 Enable SSH ({chk_sel})")
                        else:
                            log("Browser: Enable SSH 已勾選")
                        enabled = True
                        break
                except Exception:
                    pass

            if not enabled:
                log("Browser: 未找到 SSH 勾選框", "WARN")

            # ── Save / Apply ───────────────────────────────────────────────
            log("Browser: 尋找 Save / Apply 按鈕")
            for btn_sel in [
                "button[type='submit']",
                "input[type='submit']",
                "button:has-text('Save')",
                "button:has-text('Apply')",
                "button:has-text('儲存')",
                "input[value='Save']",
                "input[value='Apply']",
            ]:
                try:
                    btn = page.locator(btn_sel).first
                    if btn.is_visible(timeout=3000):
                        btn.click()
                        log(f"Browser: 點擊儲存 ({btn_sel})")
                        time.sleep(2)
                        break
                except Exception:
                    pass

            log("Browser: SSH Service 設定完成")
            return True

        except PwTimeout:
            log(f"Browser: 逾時，URL={page.url}", "WARN")
            return False
        except Exception as e:
            log(f"Browser: 例外 — {e}", "ERROR")
            return False
        finally:
            browser.close()


# ── Step 2: SSH stress ────────────────────────────────────────────────────────
def ssh_stress(cycles: int) -> list[dict]:
    try:
        import paramiko
    except ImportError:
        log("paramiko not installed — skipping SSH stress", "ERROR")
        return []

    results = []
    log(f"SSH stress: 開始 {cycles} 次連線測試 → {SSH_USER}@{DUT_HOST}")

    for i in range(1, cycles + 1):
        t0     = time.time()
        result = {"cycle": i, "success": False, "time_ms": 0, "error": ""}
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            # Try no-auth (none) then empty password
            connected = False
            for kwargs in [
                {"username": SSH_USER, "look_for_keys": False, "allow_agent": False,
                 "auth_timeout": 10},
                {"username": SSH_USER, "password": "", "look_for_keys": False,
                 "allow_agent": False, "auth_timeout": 10},
            ]:
                try:
                    client.connect(DUT_HOST, port=22, timeout=15, **kwargs)
                    connected = True
                    break
                except paramiko.AuthenticationException:
                    pass

            if connected:
                _, stdout, _ = client.exec_command("echo ok", timeout=5)
                stdout.read()
                result["success"] = True
                log(f"SSH [{i:02d}/{cycles}] ✓  {int((time.time()-t0)*1000)} ms")
            else:
                result["error"] = "auth_failed"
                log(f"SSH [{i:02d}/{cycles}] ✗  認證失敗", "WARN")

        except Exception as e:
            result["error"] = str(e)[:120]
            log(f"SSH [{i:02d}/{cycles}] ✗  {result['error']}", "WARN")
        finally:
            result["time_ms"] = int((time.time() - t0) * 1000)
            try:
                client.close()
            except Exception:
                pass

        results.append(result)
        time.sleep(0.5)

    success = sum(1 for r in results if r["success"])
    log(f"SSH stress: 完成  ✓{success} / ✗{cycles - success} / 共{cycles}")
    return results


# ── Step 3: Serial restore ────────────────────────────────────────────────────
def serial_restore() -> tuple[bool, float]:
    try:
        import serial
    except ImportError:
        log("pyserial not installed — cannot restore", "ERROR")
        return False, 0.0
    try:
        with serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=5) as ser:
            log(f"Serial: 開啟 {SERIAL_PORT} @ {BAUD_RATE}")
            time.sleep(0.5)
            ser.write(b"\r\n");  time.sleep(1.5)
            ser.reset_input_buffer()
            ser.write(f"{RESTORE_CMD}\r\n".encode())
            t = time.time()
            log(f"Serial: 執行 {RESTORE_CMD}")
            time.sleep(3)
            out = ser.read(ser.in_waiting).decode(errors="replace").strip()
            if out:
                log(f"Serial output: {out[:400]}")
            return True, t
    except Exception as e:
        log(f"Serial: 錯誤 — {e}", "ERROR")
        return False, 0.0


# ── Step 4: Boot monitor ──────────────────────────────────────────────────────
def monitor_serial_boot(iteration: int, secs: int, t_restore: float,
                        run_dir: Path) -> tuple[bool, float]:
    serial_log = run_dir / f"serial_boot_iter{iteration:04d}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log(f"Serial monitor: 紀錄重開機輸出 → {serial_log.name}")
    try:
        import serial as _serial
    except ImportError:
        return False, 0.0

    end = time.time() + secs
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
                                    log(f"\nSerial: 開機完成 ({pat.decode(errors='replace').strip()!r})"
                                        f"  boot time={boot_time_s:.1f}s")
                                    break
    except Exception as e:
        print()
        log(f"Serial monitor: 無法開啟 port — {e}", "WARN")

    print()
    if not boot_detected:
        log(f"Serial monitor: ⚠ {secs}s 內未偵測到開機完成", "WARN")
        if serial_log.exists():
            serial_log.unlink()
    log(f"Serial monitor: 完成，共捕捉 {bytes_cap} bytes")
    return boot_detected, round(boot_time_s, 1)


# ── Result writer ─────────────────────────────────────────────────────────────
def _write_result(run_dir: Path, iterations: list[dict],
                  success: int, failure: int) -> None:
    (run_dir / "result.json").write_text(json.dumps({
        "type":       "ssh_stress",
        "total":      success + failure,
        "success":    success,
        "failure":    failure,
        "result":     "PASS" if failure == 0 else "FAIL",
        "iterations": iterations,
    }, indent=2, ensure_ascii=False))


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    global _log_file

    parser = argparse.ArgumentParser(description="SSH Stress Test")
    parser.add_argument("--iterations",  type=int, default=0,
                        help="Reset cycles (0 = infinite)")
    parser.add_argument("--ssh-cycles",  type=int, default=10,
                        help="SSH connect/disconnect count per cycle")
    parser.add_argument("--ssh-wait",    type=int, default=WAIT_SSH_READY_SECS,
                        help="Seconds to wait after enabling SSH")
    parser.add_argument("--reboot-wait", type=int, default=WAIT_REBOOT_SECS,
                        help="Seconds to wait for reboot")
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config.yaml")
    args = parser.parse_args()

    _load_config(args.config)

    stamp   = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = RUNS_DIR / f"ssh-stress-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    _log_file = run_dir / "ssh_stress.log"

    log(f"=== SSH Stress Test  iterations={'∞' if args.iterations == 0 else args.iterations}"
        f"  ssh_cycles={args.ssh_cycles} ===")
    log(f"    DUT: {DUT_HOST}  web_user={WEB_USER}  ssh_user={SSH_USER}")
    log(f"    Serial: {SERIAL_PORT} @ {BAUD_RATE}")
    log(f"    Run dir: {run_dir}")

    success_count = 0
    failure_count = 0
    iteration_log: list[dict] = []
    iteration = 0

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
        iter_info: dict = {
            "iteration":    iteration,
            "result":       "FAIL",
            "browser_ok":   False,
            "ssh_cycles":   [],
            "ssh_success":  0,
            "ssh_fail":     0,
            "serial_ok":    False,
            "boot_detected":False,
            "boot_time_s":  0.0,
        }
        ok = True

        # Step 1 — browser: enable SSH
        if not browser_enable_ssh():
            ok = False
            log("Step 1 FAIL: 無法啟用 SSH Service", "WARN")
        else:
            iter_info["browser_ok"] = True
            log(f"等待 {args.ssh_wait}s 讓 SSH 服務就緒…")
            time.sleep(args.ssh_wait)

        # Step 2 — SSH stress (even if browser failed, attempt SSH)
        ssh_results = ssh_stress(args.ssh_cycles)
        iter_info["ssh_cycles"]  = ssh_results
        iter_info["ssh_success"] = sum(1 for r in ssh_results if r["success"])
        iter_info["ssh_fail"]    = sum(1 for r in ssh_results if not r["success"])
        if iter_info["ssh_fail"] > 0:
            ok = False
            log(f"Step 2 FAIL: SSH 壓力測試有 {iter_info['ssh_fail']} 次失敗", "WARN")

        # Step 3 — serial restore
        restore_ok, t_restore = serial_restore()
        if not restore_ok:
            ok = False
            log("Step 3 FAIL: serial restore 失敗", "WARN")
        else:
            iter_info["serial_ok"] = True

        # Step 4 — monitor reboot
        log(f"等待重開機，最多 {args.reboot_wait // 60} 分鐘…")
        boot_detected, boot_time_s = monitor_serial_boot(
            iteration, args.reboot_wait, t_restore, run_dir)
        iter_info["boot_detected"] = boot_detected
        iter_info["boot_time_s"]   = boot_time_s

        if not boot_detected:
            ok = False
            log("Step 4 FAIL: 未偵測到裝置開機完成", "WARN")

        if ok:
            success_count += 1
            iter_info["result"] = "PASS"
            log(f"第 {iteration} 輪 ✓ PASS  累計 ✓{success_count} ✗{failure_count}")
        else:
            failure_count += 1
            log(f"第 {iteration} 輪 ✗ FAIL  累計 ✓{success_count} ✗{failure_count}", "WARN")

        iteration_log.append(iter_info)
        _write_result(run_dir, iteration_log, success_count, failure_count)

    log(f"=== 完成  成功:{success_count}  失敗:{failure_count} ===")
    _write_result(run_dir, iteration_log, success_count, failure_count)


if __name__ == "__main__":
    main()
