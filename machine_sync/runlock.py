"""MachineSync\\run.lock: one sync run at a time, and no daily task started in the middle of one. The sync run
holds it for its whole run; the launcher holds it while it claims the day and starts a daily task, so the next sync
run already sees the task's process (design, "Daily tasks and freezes")."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

LOCK = "run.lock"
GRACE_S = 10  # a lock younger than this with no pid yet is being written, not stale
STALE_S = 3600  # a sync run never lasts longer (the scheduled task's own limit)


def pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _held(lock: Path) -> bool:
    try:
        text, age = lock.read_text().strip(), time.time() - lock.stat().st_mtime
    except OSError:
        return False
    try:
        pid = int(text)
    except ValueError:
        return age < GRACE_S
    return age < STALE_S and pid_alive(pid)


def acquire(sync_dir: Path, wait_s: float = 0.0) -> bool:
    """Take the lock, waiting up to wait_s seconds for its holder; a dead holder's lock is taken over."""
    sync_dir.mkdir(parents=True, exist_ok=True)
    lock, deadline = sync_dir / LOCK, time.time() + wait_s
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if not _held(lock):
                lock.unlink(missing_ok=True)
                continue
            if time.time() >= deadline:
                return False
            time.sleep(0.25)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True


def release(sync_dir: Path) -> None:
    """Drop the lock if this process holds it."""
    lock = sync_dir / LOCK
    try:
        if lock.read_text().strip() == str(os.getpid()):
            lock.unlink()
    except OSError:
        pass
