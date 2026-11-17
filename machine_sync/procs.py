"""Running processes with their command lines (Windows: CIM through PowerShell; the standard library has no API)."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from .gitops import NO_WINDOW

_QUERY = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ExecutablePath,CommandLine | "
          "ConvertTo-Json -Compress")


@dataclass(frozen=True)
class Proc:
    pid: int
    exe: str | None
    cmdline: str


def processes() -> list[Proc]:
    """Every process this user can see; empty when the query fails (callers then treat nothing as running)."""
    try:
        done = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _QUERY],
                              capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
                              creationflags=NO_WINDOW)
        rows = json.loads(done.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    if isinstance(rows, dict):
        rows = [rows]
    return [Proc(int(r.get("ProcessId") or 0), r.get("ExecutablePath"), r.get("CommandLine") or "") for r in rows]
