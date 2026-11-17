"""Starting, stopping, and health-checking the processes behind each app."""
import ctypes
import os
import socket
import subprocess
import urllib.error
import urllib.request
from ctypes import wintypes
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import ProcessConfig

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
_kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
PROCESS_QUERY_LIMITED_INFORMATION, ERROR_ACCESS_DENIED, STILL_ACTIVE = 0x1000, 5, 259


def pid_alive(pid: int, created_by: datetime | None = None) -> bool:
    """Whether process `pid` is running. With `created_by` (aware), only a process created no later than that counts,
    so a pid Windows has since handed to another process is not taken for the one that ended."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # it exists, run by someone else
    try:
        code = wintypes.DWORD()
        if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != STILL_ACTIVE:
            return False
        if created_by is None:
            return True
        times = [wintypes.FILETIME() for _ in range(4)]  # creation, exit, kernel, user
        if not _kernel32.GetProcessTimes(handle, *map(ctypes.byref, times)):
            return True
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime  # 100 ns since 1601 UTC
        return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=ticks // 10) <= created_by
    finally:
        _kernel32.CloseHandle(handle)


def _tcp_is_up(port: int) -> bool:
    for family, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        with socket.socket(family, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            if s.connect_ex((host, port)) == 0:
                return True
    return False


def _http_is_up(port: int, path: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=0.5) as resp:
            return 200 <= resp.status < 400
    except (urllib.error.URLError, OSError):
        return False


def is_up(proc: ProcessConfig) -> bool:
    if proc.health == "http":
        return _http_is_up(proc.port, proc.health_path)
    return _tcp_is_up(proc.port)


def find_pid_by_port(port: int) -> int | None:
    result = subprocess.run(["netstat", "-ano"], capture_output=True, text=True)
    for line in result.stdout.splitlines():
        if line.strip().startswith(("TCP", "TCP6")) and "LISTENING" in line:
            parts = line.split()
            if parts[1].rsplit(":", 1)[-1] == str(port):
                return int(parts[-1])
    return None


def start_process(proc: ProcessConfig, log_dir: Path) -> str | None:
    """Starts proc unless already up. Returns an error message on failure, else None."""
    if is_up(proc):
        return None
    log_path = log_dir / proc.log
    env = {**os.environ, **proc.env}
    try:
        with open(log_path, "a") as log_file:
            subprocess.Popen(
                proc.resolved_cmd(),
                cwd=str(proc.resolved_cwd()),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env,
            )
    except OSError as e:
        return f"{proc.log}: failed to start ({e})"
    return None


def stop_process(proc: ProcessConfig) -> None:
    pid = find_pid_by_port(proc.port)
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
