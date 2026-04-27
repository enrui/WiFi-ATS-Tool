"""
lib/devices.py
--------------
Connection abstractions for DUT (Serial + SSH) and BPI-R4 (SSH only).
Used by pytest fixtures and test cases.
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import paramiko
import pexpect
import serial
import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
@dataclass
class Config:
    raw: dict

    @classmethod
    def load(cls, path: str | Path = "config.yaml") -> "Config":
        with open(path, "r") as f:
            return cls(raw=yaml.safe_load(f))

    def get(self, dotted_key: str, default=None):
        """e.g. get('dut.host')"""
        node = self.raw
        for k in dotted_key.split("."):
            if not isinstance(node, dict) or k not in node:
                return default
            node = node[k]
        return node


# ---------------------------------------------------------------------------
# SSH client wrapper (for both DUT and BPI)
# ---------------------------------------------------------------------------
class SSHDevice:
    """Thin wrapper around paramiko with a few DUT-friendly conveniences."""

    def __init__(self, host: str, user: str,
                 password: Optional[str] = None,
                 key_path: Optional[str] = None,
                 port: int = 22,
                 name: str = "device"):
        self.host = host
        self.user = user
        self.password = password
        self.key_path = os.path.expanduser(key_path) if key_path else None
        self.port = port
        self.name = name
        self.client: Optional[paramiko.SSHClient] = None

    def connect(self, timeout: int = 10) -> None:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if self.key_path and os.path.exists(self.key_path):
            client.connect(hostname=self.host, port=self.port,
                           username=self.user, timeout=timeout,
                           key_filename=self.key_path)
        elif self.password:
            client.connect(hostname=self.host, port=self.port,
                           username=self.user, password=self.password,
                           timeout=timeout, look_for_keys=False, allow_agent=False)
        else:
            # No credentials — try SSH "none" auth (common on OpenWrt without root password)
            t = paramiko.Transport((self.host, self.port))
            t.start_client(timeout=timeout)
            try:
                t.auth_none(self.user)
            except paramiko.BadAuthenticationType:
                pass
            if not t.is_authenticated():
                raise paramiko.AuthenticationException(
                    f"[{self.name}] none-auth failed for {self.user}@{self.host}"
                )
            t.set_keepalive(60)
            client._transport = t
        self.client = client
        logger.info(f"[{self.name}] SSH connected to {self.user}@{self.host}")

    def run(self, cmd: str, timeout: int = 30, check: bool = False) -> tuple[int, str, str]:
        """
        Execute command, return (exit_code, stdout, stderr).
        Auto-reconnects once if the SSH session has dropped.
        Raises RuntimeError if check=True and exit_code != 0.
        """
        if not self.client:
            raise RuntimeError(f"[{self.name}] Not connected")
        try:
            return self._exec(cmd, timeout, check)
        except (paramiko.SSHException, EOFError) as exc:
            logger.warning(f"[{self.name}] SSH session dropped ({exc}), reconnecting…")
            self.connect()
            return self._exec(cmd, timeout, check)

    def _exec(self, cmd: str, timeout: int, check: bool) -> tuple[int, str, str]:
        logger.debug(f"[{self.name}] $ {cmd}")
        stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        if check and exit_code != 0:
            raise RuntimeError(
                f"[{self.name}] Command failed ({exit_code}): {cmd}\n"
                f"stderr: {err}"
            )
        return exit_code, out, err

    def put_file(self, local: str, remote: str) -> None:
        assert self.client
        sftp = self.client.open_sftp()
        sftp.put(local, remote)
        sftp.close()

    def get_file(self, remote: str, local: str) -> None:
        assert self.client
        sftp = self.client.open_sftp()
        sftp.get(remote, local)
        sftp.close()

    def close(self) -> None:
        if self.client:
            self.client.close()
            self.client = None
            logger.info(f"[{self.name}] SSH closed")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


# ---------------------------------------------------------------------------
# Serial console wrapper (for DUT boot logs and shell)
# ---------------------------------------------------------------------------
class SerialConsole:
    """
    Captures serial output to a log file and allows sending commands.
    All output is persisted even if the test crashes.
    """

    def __init__(self, port: str, baud: int = 115200,
                 log_path: Optional[str] = None,
                 name: str = "serial"):
        self.port = port
        self.baud = baud
        self.log_path = log_path
        self.name = name
        self._ser: Optional[serial.Serial] = None
        self._log_fp = None

    def open(self) -> None:
        self._ser = serial.Serial(self.port, self.baud, timeout=0.5)
        if self.log_path:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            self._log_fp = open(self.log_path, "a", buffering=1)
            self._log_fp.write(f"\n===== Serial opened {time.ctime()} =====\n")
        logger.info(f"[{self.name}] Opened {self.port} @ {self.baud}")

    def close(self) -> None:
        if self._ser:
            self._ser.close()
            self._ser = None
        if self._log_fp:
            self._log_fp.close()
            self._log_fp = None

    def send(self, text: str, add_newline: bool = True) -> None:
        assert self._ser
        payload = (text + ("\r\n" if add_newline else "")).encode()
        self._ser.write(payload)
        if self._log_fp:
            self._log_fp.write(f"[SEND] {text}\n")

    def read_until(self, marker: str, timeout: float = 10.0) -> str:
        """Read until marker string appears in output, or timeout."""
        assert self._ser
        buf = ""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self._ser.read(4096).decode("utf-8", errors="replace")
            if chunk:
                buf += chunk
                if self._log_fp:
                    self._log_fp.write(chunk)
                if marker in buf:
                    return buf
            else:
                time.sleep(0.1)
        raise TimeoutError(
            f"[{self.name}] Marker '{marker}' not found within {timeout}s"
        )

    def drain(self, duration: float = 2.0) -> str:
        """Read whatever arrives in the next `duration` seconds."""
        assert self._ser
        buf = ""
        deadline = time.time() + duration
        while time.time() < deadline:
            chunk = self._ser.read(4096).decode("utf-8", errors="replace")
            if chunk:
                buf += chunk
                if self._log_fp:
                    self._log_fp.write(chunk)
            else:
                time.sleep(0.1)
        return buf

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------
def make_dut_ssh(cfg: Config) -> SSHDevice:
    return SSHDevice(
        host=cfg.get("dut.host"),
        user=cfg.get("dut.ssh_user"),
        password=cfg.get("dut.ssh_password"),
        key_path=cfg.get("dut.ssh_key_path"),
        name="DUT",
    )


def make_bpi_ssh(cfg: Config) -> SSHDevice:
    return SSHDevice(
        host=cfg.get("bpi_sta.host"),
        user=cfg.get("bpi_sta.ssh_user"),
        password=cfg.get("bpi_sta.ssh_password"),
        key_path=cfg.get("bpi_sta.ssh_key_path"),
        name="BPI",
    )


def make_dut_serial(cfg: Config, log_path: Optional[str] = None) -> SerialConsole:
    return SerialConsole(
        port=cfg.get("dut.serial_port"),
        baud=cfg.get("dut.serial_baud", 115200),
        log_path=log_path,
        name="DUT-serial",
    )
