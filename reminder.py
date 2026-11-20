"""The day's reminders: a banner when a task with `remind` (tasks.yaml) has not been started by its times.

On a weekday in the task's timezone, from the first `remind.at` time on, a task is due a reminder while there is
no record for today's decision date t (`remind.record`, e.g. Trend's data/logs/sod_<t>.json), the launcher is not
running it, and its progress file does not show a live run for t. t is the weekday before today (Monday's is
Friday), as in Trend's `sod.decision_date`. The latest start comes from the task's preview (its `preview_cmd`, here
`daily_cycle.py --plan`) when that prints "start by HH:MM"; otherwise it is left out.

The IBKR cycle (team review, 20 Nov 2026, trade operations 4: the day side told nobody when a press was
forgotten) has two presses and an approval between them, and no record file until its night is over. Its `remind`
names IBKR's heartbeat file instead (`cycle_due`): once Start of Day's record for t says GO, a banner while the
heartbeat shows no run for the trade day's cycle (the first press), and while its last run ended waiting for
approval (approve on MTFA Operations, then Start trading). None while a run for it is beating or after it ended any
other way (done, halted: the cycle's own Telegram alert says so).

It only reminds: the task is still started by hand (Trend DECISIONS 2026-10-27, no scheduled task).
"""
import json
import re
from datetime import date, datetime, time, timedelta

import progress
from config import TaskConfig

START_BY = re.compile(r"start by (\d{1,2}:\d{2})", re.IGNORECASE)
# a person's deadline, as the runbook's table of the seasons gives it: the first window opens about 16:25 Sydney
# (ASX) from November to March, and the SGX mini JGB's 15:55 from April to September
FIRST_WINDOW = "before the first window (about 16:25 Sydney; 15:55 from April)"
BEATING = ("starting", "connecting", "running")


def decision_date(today: date) -> date:
    """The weekday before `today`: Monday's is Friday."""
    day = today - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _json(path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def cycle_due(task: TaskConfig, now: datetime, running: bool, day: str) -> dict | None:
    """The IBKR cycle's reminder at `now`, or None (module docstring). `day`: the trade day the task's press would
    claim (task_runner.claim_day), whose cycle is `<day>-<mode>`."""
    local = now.astimezone(progress.zone(task.timezone))
    slots = sorted(time.fromisoformat(at) for at in task.remind.at)
    passed = [s for s in slots if local.time() >= s]
    if local.weekday() >= 5 or not passed or running:
        return None
    trade = date.fromisoformat(day)
    t = decision_date(trade)
    if task.remind.go:
        sod = _json(task.resolved_go(t.isoformat()))
        if not sod or sod.get("verdict") != "GO":
            return None  # Start of Day has not said GO (its own reminder), or held: nothing to press
    beat = _json(task.resolved_heartbeat())
    cycle_id = f"{day}-{task.remind.mode}"
    stage = "first"
    if beat and beat.get("cycle_id") == cycle_id:
        if beat.get("run") in BEATING:
            # a run for it is going, here or elsewhere; one that stopped beating without ending died, which is the
            # resume task's and the VPS watch's to catch, not a press forgotten
            return None
        if beat.get("ended") != "waiting":
            return None  # done, halted, refused...: the cycle's own alert says what to do
        stage = "approval"
    when = f"{trade:%a %d %b}"
    if stage == "first":
        text = f"{task.label} for {when}: Start of Day is GO, and the first press is not done"
        note = (f"Reminder of {passed[-1]:%H:%M}: press it to build the list, then approve and press Start "
                f"trading {FIRST_WINDOW}.")
    else:
        text = f"{task.label} for {when}: the list waits for your approval"
        note = (f"Reminder of {passed[-1]:%H:%M}: approve it on MTFA Operations, then press Start trading "
                f"{FIRST_WINDOW}. Nothing trades until then.")
    return {
        "task_id": task.id,
        "t": day,  # the cycle's trade day: Dismiss hides this banner until the next reminder time
        "slot": passed[-1].strftime("%H:%M"),
        "again": len(passed) > 1,
        "latest_start": None,
        "text": text,
        "note": note,
        "stage": stage,
        "start": stage == "first",  # approval comes before the second press: no Start on the banner
        "tab": "IBKR cycle: approve" if stage == "approval" else "IBKR cycle not started",
    }


def due(task: TaskConfig, now: datetime, running: bool, prog: dict | None, preview: str = "",
        day: str | None = None) -> dict | None:
    """The reminder `task` is due at `now` (aware), or None. `running`: the launcher is running the task; `prog`: its
    progress file (progress.read); `preview`: its preview's last line; `day`: the day its press would claim (the
    IBKR cycle's trade day)."""
    if not task.remind:
        return None
    if task.remind.heartbeat:
        return cycle_due(task, now, running, day or now.astimezone(progress.zone(task.timezone)).date().isoformat())
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
