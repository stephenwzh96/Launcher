"""Sends CTRL_BREAK_EVENT to a task's process group: `python ctrl_break.py <pid>`.

The launcher starts each task with CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP, so the task has a console of its own
(with no window) and leads its own process group, whose id is its pid. A console control event reaches only processes
on the sender's console, so the launcher cannot send it directly; this helper, a process of its own, leaves its
console, attaches to the task's, and sends the event to the task's group. Every process in the group gets it (a
venv's python.exe passes it on to the interpreter it started); a Python task sees SIGBREAK.

Exit 0 = sent; 1 = could not attach (the process is gone, or has no console); 2 = the send failed.
"""
import ctypes
import sys

CTRL_BREAK_EVENT = 1


def main(pid: int) -> int:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        return 1
    sent = kernel32.GenerateConsoleCtrlEvent(CTRL_BREAK_EVENT, pid)  # this helper is not in the group: it is spared
    kernel32.FreeConsole()
    return 0 if sent else 2


if __name__ == "__main__":
    sys.exit(main(int(sys.argv[1])))
