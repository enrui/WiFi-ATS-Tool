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
import threading
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

SSH_PASSWORD         = "password"   # root password (override in config or SSH_PASSWORD env)
WAIT_SSH_READY_SECS  = 20
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
    global DUT_HOST, WEB_USER, WEB_PASSWORD, SSH_USER, SSH_PASSWORD, SERIAL_PORT, BAUD_RATE
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
        SSH_PASSWORD = dut.get("ssh_password", SSH_PASSWORD)
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
def browser_enable_ssh(run_dir: Path, iteration: int) -> bool:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
    except ImportError:
        log("playwright not installed — skipping browser step", "WARN")
        return True

    login_url  = f"http://{DUT_HOST}/login.html"
    main_url   = f"http://{DUT_HOST}/main.html"
    video_dir  = run_dir / "video"
    video_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir=str(video_dir),
            record_video_size={"width": 1280, "height": 720},
        )
        page = context.new_page()
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
            page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
            log(f"Browser: 目前 URL → {page.url}")

            # ── Click Advanced Setup tab — wait for it to be clickable ─────
            log("Browser: 等待 #menu_adv_setting_item 可點選…")
            adv = page.locator("#menu_adv_setting_item")
            adv.wait_for(state="visible", timeout=LOGIN_TIMEOUT_MS)
            adv.click()
            log("Browser: 點擊 Advanced Setup (#menu_adv_setting_item)")

            # ── Wait for SSH sub-tab to appear, then click ─────────────────
            ssh_tab = page.locator("#menu_adv_setting_ssh_item")
            ssh_tab.wait_for(state="visible", timeout=10_000)
            ssh_tab.click()
            log("Browser: 點擊 SSH (#menu_adv_setting_ssh_item)")
            time.sleep(1)

            # ── Enable SSH toggle ──────────────────────────────────────────
            # Wait for networkidle so the page JS has finished setting the
            # checkbox state — reading is_checked() too early can return
            # False even when SSH is already ON, causing us to toggle it OFF.
            try:
                page.wait_for_load_state("networkidle", timeout=10_000)
            except PwTimeout:
                pass

            chk = page.locator("#ssh_enabled")
            chk.wait_for(state="attached", timeout=10_000)

            # Read the input value directly via JS to get the true current state
            ssh_val = chk.evaluate("el => el.value")
            is_on   = ssh_val not in ("0", "false", "", "off", None)
            log(f"Browser: SSH 目前狀態 = {'ON' if is_on else 'OFF'} (value={ssh_val!r})")

            def _screenshot(tag: str) -> None:
                shot = run_dir / f"browser_{tag}_iter{iteration:04d}.png"
                try:
                    page.screenshot(path=str(shot))
                    log(f"Browser: 截圖 → {shot.name}")
                except Exception:
                    pass

            if not is_on:
                label = page.locator("label[for='ssh_enabled']")
                if label.count() > 0:
                    label.first.click()
                    log("Browser: 點擊 label[for=ssh_enabled] 開啟 toggle")
                else:
                    chk.evaluate("el => { el.checked = true; el.dispatchEvent(new Event('change', {bubbles:true})); }")
                    log("Browser: JS 設定 #ssh_enabled = true")

                # Verify via value
                time.sleep(0.5)
                val_after   = chk.evaluate("el => el.value")
                is_on_after = val_after not in ("0", "false", "", "off", None)
                log(f"Browser: toggle 後狀態 = {'ON' if is_on_after else 'OFF (異常)'} (value={val_after!r})")
                if not is_on_after:
                    _screenshot("toggle_fail")
                    log("Browser: toggle 未切換成 ON", "ERROR")
                    return False

            # ── Click Apply and wait for "Please wait..." to finish ────────
            page.locator("#apply").click()
            log("Browser: 點擊 #apply 儲存，等待 loading 完成…")
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PwTimeout:
                pass  # continue even if still loading
            _screenshot("after_apply")

            # ── Dismiss confirmation dialog (appears after loading) ────────
            try:
                dismiss = page.locator(
                    "button:has-text('關閉'), a:has-text('關閉'), "
                    "button:has-text('Close'), a:has-text('Close'), "
                    "button:has-text('OK'), a:has-text('OK')"
                ).first
                dismiss.wait_for(state="visible", timeout=5_000)
                dismiss.click()
                log("Browser: 關閉確認 dialog")
                time.sleep(0.5)
            except PwTimeout:
                log("Browser: 未出現確認 dialog，繼續")
            time.sleep(1)

            log("Browser: SSH Service 已啟用並儲存")
            return True

        except PwTimeout:
            shot = run_dir / f"browser_timeout_iter{iteration:04d}.png"
            try:
                page.screenshot(path=str(shot))
                log(f"Browser: 截圖已存 → {shot.name}", "WARN")
            except Exception:
                pass
            log(f"Browser: 逾時，URL={page.url}", "WARN")
            return False
        except Exception as e:
            log(f"Browser: 例外 — {e}", "ERROR")
            return False
        finally:
            # Close context first — this finalises the video file
            try:
                video_path = page.video.path() if page.video else None
                context.close()
                if video_path:
                    dest = video_dir / f"iter{iteration:04d}_browser.webm"
                    Path(video_path).rename(dest)
                    log(f"Browser: 錄影已存 → video/iter{iteration:04d}_browser.webm")
            except Exception:
                pass
            browser.close()


# ── Step 2: SSH stress ────────────────────────────────────────────────────────
def _ssh_once(pwd: str) -> tuple[bool, str]:
    """Single SSH connect/exec/disconnect via sshpass+ssh subprocess.
    Returns (success, error_message)."""
    import subprocess as _sp
    # sshpass -p <pwd> ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 user@host 'echo ok'
    cmd = (["sshpass", "-p", pwd] if pwd else []) + [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", f"BatchMode={'no' if pwd else 'yes'}",
        f"{SSH_USER}@{DUT_HOST}",
        "echo ok",
    ]
    try:
        r = _sp.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return True, ""
        err = (r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else f"rc={r.returncode}"
        return False, err[:120]
    except FileNotFoundError:
        return False, "sshpass not found"
    except _sp.TimeoutExpired:
        return False, "timeout"
    except Exception as e:
        return False, str(e)[:120]


def ssh_stress(cycles: int) -> list[dict]:
    # Build password candidates
    passwords: list[str] = []
    if SSH_PASSWORD:
        passwords.append(SSH_PASSWORD)
    for p in ("password", "", "admin"):
        if p not in passwords:
            passwords.append(p)

    results = []
    log(f"SSH stress: 開始 {cycles} 次連線測試 → {SSH_USER}@{DUT_HOST}")

    for i in range(1, cycles + 1):
        t0     = time.time()
        result = {"cycle": i, "success": False, "time_ms": 0, "error": ""}

        ok, err = False, ""
        for pwd in passwords:
            ok, err = _ssh_once(pwd)
            if ok or err == "sshpass not found":
                break
            # wrong password → try next; connection refused → stop early
            if "Connection refused" in err or "No route" in err:
                break

        result["time_ms"] = int((time.time() - t0) * 1000)
        result["success"]  = ok
        result["error"]    = "" if ok else err

        if ok:
            log(f"SSH [{i:02d}/{cycles}] ✓  {result['time_ms']} ms")
        else:
            log(f"SSH [{i:02d}/{cycles}] ✗  {err}", "WARN")

        results.append(result)
        time.sleep(0.5)

    success = sum(1 for r in results if r["success"])
    log(f"SSH stress: 完成  ✓{success} / ✗{cycles - success} / 共{cycles}")
    return results


# ── Serial full-session recorder ─────────────────────────────────────────────
class SerialRecorder:
    """Background thread that continuously reads the serial port and saves to a log file.
    Must be stopped before serial_restore() or monitor_serial_boot() open the same port."""

    def __init__(self, run_dir: Path, iteration: int):
        self._path = run_dir / f"serial_full_iter{iteration:04d}.log"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        try:
            import serial as _serial
        except ImportError:
            log("pyserial not installed — serial recorder skipped", "WARN")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        log(f"Serial recorder: 開始錄製 → {self._path.name}")

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop.set()
        self._thread.join(timeout=5)
        self._thread = None
        log(f"Serial recorder: 停止，已存 {self._path.name}")

    def _run(self) -> None:
        try:
            import serial as _serial
            with _serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
                with open(self._path, "wb") as f:
                    while not self._stop.is_set():
                        chunk = ser.read(ser.in_waiting or 1)
                        if chunk:
                            f.write(chunk)
                            f.flush()
        except Exception as e:
            with open(self._path, "ab") as f:
                f.write(f"\n[recorder error: {e}]\n".encode())


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
    is_tty        = sys.stdout.isatty()
    last_status_t = time.time()

    time.sleep(2)
    try:
        with _serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1) as ser:
            with open(serial_log, "wb") as sf:
                while time.time() < end:
                    remaining = int(end - time.time())
                    mm, ss = divmod(remaining, 60)
                    if is_tty:
                        status = f"boot:{boot_time_s:.0f}s ✓" if boot_detected else "等待開機…"
                        print(f"\r  {status}  剩餘 {mm:02d}:{ss:02d}  [serial: {bytes_cap} bytes]  ",
                              end="", flush=True)
                    elif time.time() - last_status_t >= 15:
                        status = f"boot:{boot_time_s:.0f}s ✓" if boot_detected else "等待開機…"
                        log(f"Serial monitor: {status}  剩餘 {mm:02d}:{ss:02d}  [{bytes_cap} bytes]")
                        last_status_t = time.time()
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
                                    log(f"Serial: 開機完成 ({pat.decode(errors='replace').strip()!r})"
                                        f"  boot time={boot_time_s:.1f}s")
                                    break
    except Exception as e:
        if is_tty:
            print()
        log(f"Serial monitor: 無法開啟 port — {e}", "WARN")

    if is_tty:
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
    parser.add_argument("--no-reset", action="store_true",
                        help="Skip restore_to_default and reboot steps")
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
        step_ok = [True, True, True, True]   # [browser, ssh, serial, boot]

        # ── Serial recorder: start at beginning of iteration ──────────────
        recorder = SerialRecorder(run_dir, iteration)
        recorder.start()

        # ── Step 1: Browser — enable SSH ──────────────────────────────────
        if not browser_enable_ssh(run_dir, iteration):
            step_ok[0] = False
            log("Step 1 FAIL: 無法啟用 SSH Service", "WARN")
        else:
            iter_info["browser_ok"] = True
            log(f"等待 {args.ssh_wait}s 讓 SSH 服務就緒…")
            time.sleep(args.ssh_wait)

        # ── Step 2: SSH stress — only if Step 1 passed ────────────────────
        if step_ok[0]:
            ssh_results = ssh_stress(args.ssh_cycles)
            iter_info["ssh_cycles"]  = ssh_results
            iter_info["ssh_success"] = sum(1 for r in ssh_results if r["success"])
            iter_info["ssh_fail"]    = sum(1 for r in ssh_results if not r["success"])
            if not ssh_results or iter_info["ssh_fail"] > 0:
                step_ok[1] = False
                log(f"Step 2 FAIL: SSH 壓力測試有 {iter_info['ssh_fail']} 次失敗"
                    f"（共 {len(ssh_results)} 次）", "WARN")
        else:
            step_ok[1] = False
            log("Step 2 SKIP: browser 未成功，跳過 SSH stress", "WARN")

        # ── Stop serial recorder before restore/monitor claim the port ─────
        recorder.stop()

        # ── Step 3 & 4: Serial restore + reboot (skipped if --no-reset) ────
        if args.no_reset:
            log("Step 3 SKIP: --no-reset，略過 restore_to_default")
            log("Step 4 SKIP: --no-reset，略過重開機偵測")
            iter_info["serial_ok"]    = None   # N/A
            iter_info["boot_detected"] = None  # N/A
        else:
            restore_ok, t_restore = serial_restore()
            if not restore_ok:
                step_ok[2] = False
                log("Step 3 FAIL: serial restore 失敗", "WARN")
            else:
                iter_info["serial_ok"] = True

            log(f"等待重開機，最多 {args.reboot_wait // 60} 分鐘…")
            boot_detected, boot_time_s = monitor_serial_boot(
                iteration, args.reboot_wait, t_restore if restore_ok else time.time(),
                run_dir)
            iter_info["boot_detected"] = boot_detected
            iter_info["boot_time_s"]   = boot_time_s
            if not boot_detected:
                step_ok[3] = False
                log("Step 4 FAIL: 未偵測到裝置開機完成", "WARN")

        ok = all(step_ok)

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
