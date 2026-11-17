"""A task's progress file: what a task writes about its own run while it runs (schema sod_progress/1).

Trend's Start of Day (`daily_cycle.py`) writes `data/logs/sod_progress.json` atomically at each step start, at least
every 15 s while a step prints output, and at the end:

    {"schema": "sod_progress/1", "pid": int, "decision_date": "YYYY-MM-DD",
     "state": "running" | "done" | "hold" | "failed" | "stopped", "step": int, "steps": int, "step_title": str,
     "started_utc": ISO, "step_started_utc": ISO, "last_output_utc": ISO, "eta_utc": ISO | null,
     "cutoff_local": "HH:MM", "deliver_by_local": "HH:MM", "on_battery": bool, "log": path}

The launcher reads it for the step, the time since the last output and the ETA, and calls a run *stalled* (running,
no output for more than STALL_MIN minutes) or *abandoned* (running, but its process is gone: killed, or the machine
restarted). `pid` is the task's own interpreter, not the process the launcher started (a venv's python.exe starts
the real one as its child), so a file is matched to a launcher run by its start time, not its pid.
"""
import json
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from process_control import pid_alive

SCHEMA = "sod_progress/1"
STALL_MIN = 10
PID_SLACK = timedelta(seconds=60)  # the process starts a little before it first writes started_utc


def zone(name: str | None) -> tzinfo:
    """The named time zone (tasks.yaml `timezone`), or this machine's when none is named or it is unknown."""
    if name:
        try:
            return ZoneInfo(name)
        except ZoneInfoNotFoundError:  # no tzdata in the venv: requirements.lock.txt has it
            print(f"[launcher] WARNING: unknown time zone {name!r}; using this machine's")
    return datetime.now().astimezone().tzinfo


def when(text) -> datetime | None:
    """An ISO time from the file, as an aware time (no offset = UTC); None when missing or unreadable."""
    if not isinstance(text, str) or not text:
        return None
    try:
        out = datetime.fromisoformat(text)
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=UTC)


def _clock(text, day: date, tz: tzinfo) -> datetime | None:
    """"HH:MM" on `day` in `tz`."""
    try:
        return datetime.combine(day, time.fromisoformat(text), tzinfo=tz)
    except (TypeError, ValueError):
        return None


def read(path: Path | None) -> dict | None:
    """The progress file, or None when there is none, it cannot be read, or it is not schema sod_progress/1."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else None


def live(p: dict) -> bool:
    """The process that writes the file is still running."""
    began = when(p.get("started_utc"))
    return pid_alive(p.get("pid"), began + PID_SLACK if began else None)


def view(p: dict, now: datetime, tz: tzinfo) -> dict:
    """What the page shows from a progress file at `now`; clock times (ETA, deliver-by) in `tz`, the task's."""
    running = p.get("state") == "running"
    began = when(p.get("started_utc"))
    last = when(p.get("last_output_utc")) or when(p.get("step_started_utc")) or began
    idle = (now - last).total_seconds() / 60 if last else None
    abandoned = running and not live(p)
    eta = when(p.get("eta_utc"))
    deliver_by = _clock(p.get("deliver_by_local"), (began or now).astimezone(tz).date(), tz)
    k, n = p.get("step"), p.get("steps")
    step = (
        {"k": k, "n": n, "title": str(p.get("step_title") or "")}
        if isinstance(k, int) and isinstance(n, int) and 0 < k <= n
        else None
    )
    return {
        "state": p.get("state"),
        "decision_date": p.get("decision_date"),
        "step": step,
        "idle_min": max(0, int(idle)) if idle is not None else None,
        "eta": eta.astimezone(tz).strftime("%H:%M") if eta else None,
        "deliver_by": p.get("deliver_by_local"),
        "cutoff": p.get("cutoff_local"),
        # still running past deliver-by, or an ETA after it; a past ETA counts as now
        "late": bool(running and not abandoned and deliver_by and max(eta or now, now) > deliver_by),
        "on_battery": bool(p.get("on_battery")),
        "stalled": bool(running and not abandoned and idle is not None and idle > STALL_MIN),
        "abandoned": abandoned,
    }
