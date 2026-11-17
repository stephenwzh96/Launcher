"""The Start of Day reminder: a banner when a task with `remind` (tasks.yaml) has not been started by its times.

On a weekday in the task's timezone, from the first `remind.at` time on, a task is due a reminder while there is
no record for today's decision date t (`remind.record`, e.g. Trend's data/logs/sod_<t>.json), the launcher is not
running it, and its progress file does not show a live run for t. t is the weekday before today (Monday's is
Friday), as in Trend's `sod.decision_date`. The latest start comes from the task's preview (its `preview_cmd`, here
`daily_cycle.py --plan`) when that prints "start by HH:MM"; otherwise it is left out.

It only reminds: the task is still started by hand (Trend DECISIONS 2026-10-27, no scheduled task).
"""
import re
from datetime import date, datetime, time, timedelta

import progress
from config import TaskConfig

START_BY = re.compile(r"start by (\d{1,2}:\d{2})", re.IGNORECASE)


def decision_date(today: date) -> date:
    """The weekday before `today`: Monday's is Friday."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def due(task: TaskConfig, now: datetime, running: bool, prog: dict | None, preview: str = "") -> dict | None:
    """The reminder `task` is due at `now` (aware), or None. `running`: the launcher is running the task; `prog`: its
    progress file (progress.read); `preview`: its preview's last line."""
    if not task.remind:
        return None
    local = now.astimezone(progress.zone(task.timezone))
    slots = sorted(time.fromisoformat(at) for at in task.remind.at)
    passed = [s for s in slots if local.time() >= s]
    if local.weekday() >= 5 or not passed or running:
        return None
    t = decision_date(local.date())
    if task.resolved_record(t.isoformat()).exists():
        return None
    if prog and prog.get("decision_date") == t.isoformat() and prog.get("state") == "running" and progress.live(prog):
        return None  # started outside the launcher (or before it restarted), and still going
    found = START_BY.search(preview or "")
    latest = found.group(1) if found else None
    return {
        "task_id": task.id,
        "t": t.isoformat(),
        "slot": passed[-1].strftime("%H:%M"),  # the reminder time it belongs to: Dismiss hides it until the next
        "again": len(passed) > 1,  # a later reminder than the first
        "latest_start": latest,
        "text": f"{task.label} for {t:%a %d %b} not started" + (f"; latest start {latest}" if latest else ""),
    }
