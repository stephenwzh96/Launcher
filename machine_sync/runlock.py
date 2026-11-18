"""MachineSync\\run.lock: one sync run at a time, and no daily task started in the middle of one. The sync run
holds it for its whole run; the launcher holds it while it claims the day and starts a daily task, so the next sync
run already sees the task's process (design, "Daily tasks and freezes").

The lock is an OS lock on one byte of the file (msvcrt.locking on Windows, fcntl elsewhere), held through an open
file for as long as the holder holds it: Windows releases it when the holder's process ends, crashed or not, and two
starters can never both take it. The file still holds the holder's pid, for messages and for older copies of this
module (the other one of the launcher and the sync tool may run one for a while after an update), which create the
file exclusively and judge it by its pid alone. So a file with no OS lock but a live pid written after that process
started is an older holder's, and is honoured; an older copy sees the pid of a holder here, and waits."""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

LOCK = "run.lock"
GRACE_S = 10  # a lock younger than this with no pid yet is being written, not stale
STALE_S = 3600  # a sync run never lasts longer (the scheduled task's own limit)
LOCK_OFFSET = 1 << 30  # the byte locked: far past the pid, so reading the pid is never blocked
RELEASED = b"0"  # what a holder leaves when it lets go (an older copy reads pid 0 as no holder)

_held: dict[str, int] = {}  # lock path -> the open file through which this process holds it


def _created(pid: int) -> float | None:
    """When process pid started (Unix time); None when that cannot be read."""
    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        times = [wintypes.FILETIME() for _ in range(4)]  # creation, exit, kernel, user
        if not k32.GetProcessTimes(handle, *map(ctypes.byref, times)):
            return None
        ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime  # 100 ns since 1601
        return ticks / 1e7 - 11644473600
    finally:
        k32.CloseHandle(handle)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
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


def _pid_holds(text: str, written: float) -> bool:
    """What the file says, judged as an older copy of this module would (no OS lock to go by): a live pid written
    within STALE_S, and not a pid Windows has since handed to a process started after it was written; an empty or
    unreadable file only while it is being written."""
    age = time.time() - written
    try:
        pid = int(text)
    except ValueError:
        return age < GRACE_S
    if age >= STALE_S or not pid_alive(pid):
        return False
    started = _created(pid)
    return started is None or started <= written + 2


def _os_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl

    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, LOCK_OFFSET)
        return True
    except OSError:
        return False


def _os_unlock(fd: int) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.lockf(fd, fcntl.LOCK_UN, 1, LOCK_OFFSET)
    except OSError:
        pass


def _take(lock: Path) -> bool:
    """One try: True when this process now holds the lock."""
    flags = os.O_RDWR | getattr(os, "O_BINARY", 0)
    try:
        fd, created = os.open(lock, flags | os.O_CREAT | os.O_EXCL), True
    except FileExistsError:
        try:
            fd, created = os.open(lock, flags), False
        except OSError:  # its last holder is removing it, or no access: busy this time
            return False
    except OSError:
        return False
    locked = kept = False
    try:
        locked = _os_lock(fd)
        if not locked:
            return False  # a holder on this module's rules
        st = os.fstat(fd)
        try:
            here = os.stat(lock)
        except OSError:
            return False
        if (st.st_ino, st.st_dev) != (here.st_ino, here.st_dev):
            return False  # its last holder removed this file meanwhile: try the new one
        os.lseek(fd, 0, os.SEEK_SET)
        text = os.read(fd, 64).decode("ascii", errors="replace").strip()
        if not (created and not text) and text != RELEASED.decode() and _pid_holds(text, st.st_mtime):
            return False  # held by an older copy of this module (or one is writing its pid right now)
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        _held[str(lock)] = fd
        kept = True
        return True
    finally:
        if not kept:
            if locked:
                _os_unlock(fd)
            os.close(fd)


def acquire(sync_dir: Path, wait_s: float = 0.0) -> bool:
    """Take the lock, waiting up to wait_s seconds for its holder. A holder that died left no OS lock: taken over."""
    sync_dir.mkdir(parents=True, exist_ok=True)
    lock, deadline = sync_dir / LOCK, time.time() + wait_s
    while True:
        if str(lock) not in _held and _take(lock):
            return True
        if time.time() >= deadline:
            return False
        time.sleep(0.25)


def holder_pid(sync_dir: Path) -> int | None:
    """The pid in the lock file (for messages), or None."""
    try:
        pid = int((sync_dir / LOCK).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid or None


def release(sync_dir: Path) -> None:
    """Drop the lock if this process holds it: the file says nobody, the OS lock goes, then the file (an older copy
    can then create it again). On Windows the file cannot go while another starter has it open: it stays, saying
    nobody holds it."""
    lock = sync_dir / LOCK
    fd = _held.pop(str(lock), None)
    if fd is None:
        return
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        os.ftruncate(fd, 0)
        os.write(fd, RELEASED)
        if sys.platform != "win32":
            os.unlink(lock)  # while still held: a waiter that opened this file then sees it is gone
    except OSError:
        pass
    finally:
        _os_unlock(fd)
        os.close(fd)
    if sys.platform == "win32":
        try:
            os.unlink(lock)
        except OSError:
            pass
