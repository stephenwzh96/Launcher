"""A daily task's run on the PC that holds today's day, as the other PCs' pages show it.

Stephen, 23 Nov 2026: "if desktop or laptop run the daily job the other 2 pc should show the updated daily status" (and
"make them consistent": the same on all three). Before, a PC that did not hold the day showed only its own history
("0 of 2 done today", "Last done 2026-11-20") while the VPS had run Start of Day and was trading.

Two sources, each a task's own:
- Start of Day (tasks.yaml `remind.record`): its record for the decision date t says GO or HOLD once it has ended, and
  its progress file says how far it is while it runs. Both are data files that Machine sync brings from the holder
  within about 5 minutes.
- The IBKR cycle (tasks.yaml `elsewhere_cmd`): a read-only command (IBKR's `python -m src.operations day`) reads the
  trade day's cycle from the shared database. It takes a few seconds, so it runs in the background and is cached for
  CMD_TTL_S; the page shows the last answer meanwhile.
"""
from __future__ import annotations

import json
import subprocess
import threading
import time
from datetime import UTC, date, datetime

import progress
import reminder
from config import TaskConfig

STALE_MIN = 15  # a progress file not written for this long is no longer news of a live run (Machine sync: 5 min)
CMD_TTL_S = 60
CMD_TIMEOUT_S = 45
NO_WINDOW = 0x08000000  # Windows: no console flashes up for the background command


def _hhmm(at: datetime | None, task: TaskConfig) -> str:
    return at.astimezone(progress.zone(task.timezone)).strftime("%H:%M") if at else ""


def from_record(task: TaskConfig, today: date, now: datetime, holder: str) -> dict:
    """Start of Day on `holder` for today's decision date: done (GO), failed (HOLD), running or not started."""
    t = reminder.decision_date(today).isoformat()
    record = task.resolved_record(t)
    if record is not None and record.exists():
        try:
            doc = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        verdict = str(doc.get("verdict") or "").upper()
        at = _hhmm(progress.when(doc.get("finished")), task)
        when = f" at {at}" if at else ""
        if verdict == "HOLD":
            return {"holder": holder, "state": "failed",
                    "text": f"HOLD on the {holder}{when}: no trade files today, IBKR keeps yesterday's positions"}
        return {"holder": holder, "state": "done", "text": f"Done on the {holder}{when}: {verdict or 'finished'}"}
    p = progress.read(task.resolved_progress_file())
    if p and p.get("decision_date") == t and p.get("state") == "running":
        last = (progress.when(p.get("last_output_utc")) or progress.when(p.get("step_started_utc"))
                or progress.when(p.get("started_utc")))
        idle = (now - last).total_seconds() / 60 if last else None
        k, n = p.get("step"), p.get("steps")
        step = f", step {k} of {n}: {p.get('step_title') or ''}".rstrip(": ") if isinstance(k, int) and isinstance(
            n, int) else ""
        if idle is not None and idle > STALE_MIN:
            return {"holder": holder, "state": "stalled",
                    "text": f"Running on the {holder}{step}, but no news for {int(idle)} min"}
        return {"holder": holder, "state": "running", "text": f"Running on the {holder}{step}"}
    return {"holder": holder, "state": "todo", "text": f"Not started on the {holder} yet"}


def from_cycle(answer: dict, task: TaskConfig, holder: str) -> dict:
    """The IBKR cycle on `holder`, from IBKR's `day` command: not started, waiting for approval, trading, done or
    halted."""
    c = answer.get("cycle")
    if not c:
        return {"holder": holder, "state": "todo", "text": f"Not started on the {holder} yet"}
    step, status = c.get("step") or "", c.get("status") or ""
    approved = progress.when(c.get("approved_at"))
    by = f"; approved by {c.get('approved_by')} at {_hhmm(approved, task)}" if approved else ""
    if status == "done":
        return {"holder": holder, "state": "done",
                "text": f"Done on the {holder} at {_hhmm(progress.when(c.get('updated_at')), task)}{by}"}
    if status == "halted":
        why = str(c.get("halt") or "")[:160]
        return {"holder": holder, "state": "failed", "text": f"Halted on the {holder} at {step}: {why}"}
    if status == "waiting" and not approved:
        return {"holder": holder, "state": "running",
                "text": f"Waiting for your approval on the {holder} (Telegram, or MTFA Operations)"}
    return {"holder": holder, "state": "running", "text": f"Running on the {holder}: {step}{by}"}


class Elsewhere:
    """The holder's run of each task, for TaskRunner.status. `run` runs a command and returns its stdout (a fake in the
    tests)."""

    def __init__(self, run=None, ttl_s: float = CMD_TTL_S) -> None:
        self.run = run or _run
        self.ttl_s = ttl_s
        self.lock = threading.Lock()
        self.cache: dict[tuple[str, str], tuple[float, dict]] = {}  # (task id, day) -> (when, view)
        self.busy: set[tuple[str, str]] = set()

    def view(self, task: TaskConfig, day: str, today: date, holder: str, now: datetime | None = None,
             wait: bool = False) -> dict | None:
        """What the page shows for `task` while `holder` holds `day`; None for a task with neither source. With
        `wait` (the tests) a command is run at once instead of in the background."""
        now = now or datetime.now(UTC)
        if task.elsewhere_cmd:
            return self._from_cmd(task, day, holder, wait)
        if task.remind and task.remind.record:
            return from_record(task, today, now, holder)
        return None

    def _from_cmd(self, task: TaskConfig, day: str, holder: str, wait: bool) -> dict:
        key = (task.id, day)
        with self.lock:
            hit = self.cache.get(key)
            fresh = hit is not None and time.monotonic() - hit[0] < self.ttl_s
            start = not fresh and key not in self.busy
            if start:
                self.busy.add(key)
        if start:
            if wait:
                self._refresh(task, day, holder, key)
            else:
                threading.Thread(target=self._refresh, args=(task, day, holder, key), daemon=True).start()
        with self.lock:
            hit = self.cache.get(key)
        if hit is None:
            return {"holder": holder, "state": "todo", "text": f"Checking the {holder}'s run…"}
        return {**hit[1], "holder": holder}

    def _refresh(self, task: TaskConfig, day: str, holder: str, key: tuple[str, str]) -> None:
        try:
            out = self.run(task.resolved_elsewhere_cmd(day), str(task.resolved_cwd()))
            lines = [ln for ln in (out or "").splitlines() if ln.strip()]
            view = from_cycle(json.loads(lines[-1]), task, holder)
        except Exception as exc:  # noqa: BLE001 - the page says it could not tell; the next look tries again
            view = {"holder": holder, "state": "todo",
                    "text": f"The {holder} holds today; its run could not be read here ({type(exc).__name__})"}
        with self.lock:
            self.cache[key] = (time.monotonic(), view)
            self.busy.discard(key)


def _run(cmd: list[str], cwd: str) -> str:
    done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=CMD_TIMEOUT_S, check=True,
                          creationflags=NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
    return done.stdout
