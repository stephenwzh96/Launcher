"""Running the one-shot Start of Day tasks in tasks.yaml: start, stop, progress, and "done today".

Unlike apps, a task ends. Each run writes its own log (logs/tasks/<id>_<time>.log), and the last run of every task
is kept in logs/tasks_state.json, so "done today" and the last result survive a launcher restart. Progress comes
from the log: the latest line containing "== k/n Title"; a task with a progress file (tasks.yaml `progress_file`,
progress.py) adds the time since its last output, its ETA, and whether it has stalled or been abandoned.

Stop asks first: each task runs in its own process group, which Stop sends CTRL_BREAK_EVENT, so a task can record
why it ended (Trend's Start of Day records "stopped" and a FAILED day). Only if it has not ended STOP_GRACE_S
later is it ended by force (taskkill /T /F).
"""
import json
import os
import re
import subprocess
import threading
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import progress
import reminder
from config import TaskConfig, claim_day_rule
from machine_sync import claims as day_claims
from machine_sync import runlock as sync_lock
from machine_sync import startcheck
from machine_sync.daily import read_claims, record_claim
from machine_sync.settings import Settings, syncthing_folders
from process_control import pid_alive, send_ctrl_break

HERE = Path(__file__).resolve().parent
SYNC_DIR = Path(os.environ.get("USERPROFILE", r"C:\Users\User")) / "MachineSync"
SYNC_WAIT_S = 120  # a sync run takes seconds; its first run on a PC about a minute

PROGRESS = re.compile(r"== (\d+)/(\d+) (.+)")
TAIL_BYTES = 64_000
SLACK = timedelta(seconds=60)
STOP_GRACE_S = 20
# no window, and a process group of its own, which Stop can send CTRL_BREAK_EVENT without reaching the launcher
START_FLAGS = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP


def _aware(text: str) -> datetime:
    """A time from tasks_state.json: naive local before started_utc was kept."""
    out = datetime.fromisoformat(text)
    return out if out.tzinfo else out.astimezone()


def _run_start(run: dict) -> datetime:
    return _aware(run.get("started_utc") or run["started"])


def _tail(path: Path, max_bytes: int = TAIL_BYTES) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def _weekday_back(day: date) -> date:
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def _next_weekday(day: date) -> date:
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def claim_day(task: TaskConfig, now: datetime) -> str:
    """The day a press at `now` claims (YYYY-MM-DD). With `claim_day` ("18:00 America/New_York"): the trade day of
    the run, the weekday after the latest weekday whose 18:00 New York has passed (IBKR's `default_trade_day`), so
    the paper cycle's presses from its first (16:00 Sydney) until 18:00 New York the next morning share Start of
    Day's day. That is 10:00 Sydney from November to March but 08:00 from April to October (09:00 in the weeks
    between): nothing here assumes the reconcile's time. Otherwise today's date in the task's time zone."""
    if not task.claim_day:
        return now.astimezone(progress.zone(task.timezone)).strftime("%Y-%m-%d")
    clock, zone = claim_day_rule(task.claim_day)
    there = now.astimezone(zone)
    decided = _weekday_back(there.date() - timedelta(days=0 if there.time() >= clock else 1))
    return _next_weekday(decided).isoformat()


def _claim_on_github(task: TaskConfig, day: str, machine: str, take_over: bool,
                     heads: dict[str, str] | None = None) -> day_claims.ClaimResult:
    return day_claims.claim(HERE, task.claim, day, machine, take_over=take_over, heads=heads)


def _prune_on_github() -> None:
    day_claims.prune(HERE)


class TaskRunner:
    def __init__(self, tasks: list[TaskConfig], log_dir: Path, stop_grace_s: float = STOP_GRACE_S,
                 claimer=_claim_on_github, sync_dir: Path = SYNC_DIR, pruner=None):
        self.tasks = {t.id: t for t in tasks}
        self.stop_grace_s = stop_grace_s
        self.claimer = claimer  # (task, day, machine, take_over, heads=) -> ClaimResult
        # deletes old claims from GitHub after a claimed start, in the background; only beside the real claimer, so a
        # runner with a stand-in claimer (tests) never reaches GitHub
        self.pruner = pruner or (_prune_on_github if claimer is _claim_on_github else (lambda: None))
        self.sync_dir = Path(sync_dir)
        self.refusals: dict[str, str] = {}  # task id -> the PC holding today's claim, after a refused start
        # task id -> what the page may offer after a refused start: "take_over" (another PC holds the day),
        # "start_anyway" (this PC is not in step: allow_unsynced=True), "take_over_anyway" (the other PC may still
        # be running: force_take_over=True)
        self.offers: dict[str, str] = {}
        self.start_lock = threading.Lock()
        self.sync_wait_s = SYNC_WAIT_S
        self.log_dir = log_dir / "tasks"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = log_dir / "tasks_state.json"
        self.procs: dict[str, subprocess.Popen] = {}
        self.lock = threading.Lock()
        self.queue: list[str] = []  # ids still to run in the current "Run all"
        self.runs: dict[str, dict] = {}
        if self.state_path.exists():
            self.runs = json.loads(self.state_path.read_text())

    # ----- state -----
    def _save(self) -> None:
        self.state_path.write_text(json.dumps(self.runs, indent=2))

    def _settle(self, task_id: str) -> None:
        """Turn a finished process into done/failed, or stopped when Stop asked it to end. A run whose process this
        launcher did not start (it was restarted mid-run) is followed by its pid; when that ends the result is
        unknown."""
        run = self.runs.get(task_id)
        if not run or run["state"] != "running":
            return
        proc = self.procs.get(task_id)
        if proc is not None:
            code = proc.poll()
            if code is None:
                return
            state = "stopped" if run.get("stopping") else "done" if code == 0 else "failed"
            run.update(state=state, exit_code=code)
            self.procs.pop(task_id)
        elif pid_alive(run["pid"], _run_start(run) + SLACK):
            return
        else:
            run.update(state="stopped" if run.get("stopping") else "unknown")
        run["finished"] = datetime.now().isoformat(timespec="seconds")
        self._save()

    # ----- the day's claim (one daily run per day across both PCs) -----
    def _machine(self) -> str | None:
        try:
            return (self.sync_dir / "machine.txt").read_text(encoding="utf-8").strip() or None
        except OSError:
            return None

    def _day(self, task: TaskConfig, now: datetime | None = None) -> str:
        return claim_day(task, now or datetime.now(UTC))

    def _sync_cfg(self, machine: str) -> Settings:
        """The sync's view of this PC: home is the folder above MachineSync (in tests, a temp folder)."""
        home = self.sync_dir.parent
        return Settings(home=home, machine=machine,
                        syncthing_folders=syncthing_folders(home, os.environ.get("LOCALAPPDATA")))

    def _task_repos(self, cfg: Settings, task: TaskConfig) -> list[str]:
        return startcheck.task_repos(cfg, str(task.resolved_cwd()), task.resolved_cmd())

    def _check_in_step(self, task: TaskConfig, cfg: Settings) -> str | None:
        """None when this PC is in step, else why not (start anyway: the page asks again and passes allow_unsynced):
        every repo the task uses (and the launcher) is on its default branch with nothing uncommitted in tracked
        files, nothing unpushed and nothing split from GitHub (H1); the other PC's newer data in the daily tasks'
        repos has arrived (M7); the sync updated the libraries of the task's repos after their last code change
        (L13)."""
        lines = startcheck.code_problems(cfg, self._task_repos(cfg, task))
        lines += startcheck.libraries_pending(cfg, startcheck.task_repos(cfg, str(task.resolved_cwd()),
                                                                         task.resolved_cmd(), launcher=False))
        daily = {r for t in self.tasks.values() if t.claim for r in self._task_repos(cfg, t)}
        if waiting := startcheck.data_pending(cfg, daily):
            lines.append(waiting)
        if not lines:
            return None
        return (f"{task.label}: this PC is not in step with GitHub's main and the {cfg.peer}, so today's run would "
                "use other code or data:\n" + "\n".join(f"- {ln}" for ln in lines)
                + "\nFix that and start again, or start anyway.")

    def _check_peer_idle(self, task: TaskConfig, cfg: Settings) -> str | None:
        """Before a take-over: None unless the other PC's sync says it is on (ran within 15 minutes) or running a
        daily task (fencing: the claim alone cannot stop a run that is still going there)."""
        labels = {t.id: t.label for t in self.tasks.values()}
        found = startcheck.peer_busy(cfg, time.time(), labels)
        if not found:
            return None
        return (f"{task.label}: not taken over: the {cfg.peer} may still be running today's daily run: "
                + "; ".join(found) + ". Two runs on one day can send duplicate orders. Take over anyway only if "
                f"you have checked that the {cfg.peer}'s run has ended (its launcher, or the execution dashboard).")

    @staticmethod
    def _guarded(check, task: TaskConfig, cfg: Settings) -> str | None:
        """A start check that failed to run refuses (the page then offers to go ahead anyway), never crashes."""
        try:
            return check(task, cfg)
        except Exception as err:  # noqa: BLE001 - a check must not take the launcher's start down
            return f"{task.label}: could not check this ({type(err).__name__}: {err})."

    def _check_claim(self, task: TaskConfig, take_over: bool, machine: str,
                     heads: dict[str, str] | None = None) -> str | None:
        """None when this PC holds today's claim for the task (claiming it now if nobody does), else why not."""
        day = self._day(task)
        res = self.claimer(task, day, machine, take_over, heads=heads)
        if res.ok:
            record_claim(self.sync_dir, task.claim, day, machine, res.at or datetime.now().isoformat(timespec="seconds"))
            return None
        if res.holder:
            self.refusals[task.id] = res.holder
            self.offers[task.id] = "take_over"
            record_claim(self.sync_dir, task.claim, day, res.holder, res.at or "")
            when = f" at {res.at[11:16]}" if res.at and len(res.at) >= 16 else ""
            return (f"{task.label} for {day} was already started on {res.holder}{when}. "
                    "Use Take over only if that run has ended or that PC is off.")
        return f"{task.label}: could not check GitHub for today's run ({res.error}); not started."

    def _held_elsewhere(self, task: TaskConfig, now: datetime) -> bool:
        day, machine = self._day(task, now), self._machine()
        return any(c["claim"] == task.claim and c["day"] == day and c["holder"] != machine
                   for c in read_claims(self.sync_dir))

    # ----- actions -----
    def start(self, task_id: str, take_over: bool = False, allow_unsynced: bool = False,
              force_take_over: bool = False) -> str | None:
        """Starts the task unless it is already running, or (a task with `claim`) another PC holds today's claim, or
        this PC is not in step (a repo the task uses is off its default branch, has edited tracked files, commits
        not on GitHub or is split from it: allow_unsynced starts it anyway). A take-over is refused while the other
        PC's sync says it is on or running a daily task (force_take_over, a second confirmation, overrides it). A
        daily task starts only between sync runs (MachineSync\\run.lock, held while claiming and starting), so the
        next sync run already sees it running. The claim goes to GitHub outside self.lock: the page's status stays
        live meanwhile. Returns an error message on failure, else None; self.offers says what the page may offer
        next."""
        task = self.tasks[task_id]
        with self.start_lock:  # one start at a time (the page and a Run all)
            with self.lock:
                self._settle(task_id)
                self.refusals.pop(task_id, None)
                self.offers.pop(task_id, None)
                if self.runs.get(task_id, {}).get("state") == "running":
                    return f"{task.label} is already running"
            if not task.claim:
                with self.lock:
                    return self._spawn(task_id, task)
            machine = self._machine()
            if not machine:
                return (f"{task.label}: this PC has no sync tool installed ({self.sync_dir}\\machine.txt is missing), "
                        "so it cannot check that the other PC has not started today's run; not started.")
            if not sync_lock.acquire(self.sync_dir, wait_s=self.sync_wait_s):
                pid = sync_lock.holder_pid(self.sync_dir)
                return (f"{task.label}: this PC's sync is busy (MachineSync\\run.lock"
                        f"{f', process {pid}' if pid else ''}) and did not finish in {self.sync_wait_s:.0f} s; "
                        "not started. Try again in a minute.")
            try:
                try:
                    cfg = self._sync_cfg(machine)
                except ValueError as err:  # machine.txt names neither desktop nor laptop
                    return f"{task.label}: {self.sync_dir}\\machine.txt is not right ({err}); not started."
                if not allow_unsynced and (refused := self._guarded(self._check_in_step, task, cfg)):
                    self.offers[task_id] = "start_anyway"
                    return refused
                if take_over and not force_take_over and (refused := self._guarded(self._check_peer_idle, task, cfg)):
                    self.offers[task_id] = "take_over_anyway"
                    return refused
                heads = startcheck.heads(cfg, self._task_repos(cfg, task))  # into the claim: what the run ran
                if refused := self._check_claim(task, take_over, machine, heads):
                    return refused
                with self.lock:
                    failed = self._spawn(task_id, task)
            finally:
                sync_lock.release(self.sync_dir)
            if failed is None:  # housekeeping on GitHub: never on the start's path, never under run.lock
                threading.Thread(target=self._prune, daemon=True).start()
            return failed

    def _prune(self) -> None:
        try:
            self.pruner()
        except Exception:  # noqa: BLE001 - best effort: the next claimed start prunes again
            pass

    def _spawn(self, task_id: str, task: TaskConfig) -> str | None:
        """Start the task's process (self.lock held)."""
        now = datetime.now()
        log_path = self.log_dir / f"{task_id}_{now:%Y%m%d-%H%M%S}.log"
        env = {**os.environ, "PYTHONUNBUFFERED": "1", **task.env}
        try:
            with open(log_path, "w", encoding="utf-8") as log_file:
                proc = subprocess.Popen(
                    task.resolved_cmd(),
                    cwd=str(task.resolved_cwd()),
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=START_FLAGS,
                    env=env,
                )
        except OSError as e:
            return f"{task.label}: failed to start ({e})"
        self.procs[task_id] = proc
        self.runs[task_id] = {
            "state": "running",
            "started": now.isoformat(timespec="seconds"),
            "started_utc": now.astimezone(UTC).isoformat(timespec="seconds"),
            "finished": None,
            "exit_code": None,
            "pid": proc.pid,
            "log": log_path.name,
        }
        self._save()
        return None

    def stop(self, task_id: str) -> None:
        """Asks the run to end (CTRL_BREAK_EVENT to its process group), and ends it by force if it is still going
        STOP_GRACE_S later. Returns at once; the row shows Stopping meanwhile."""
        with self.lock:
            self.queue.clear()  # stopping one task also ends a "Run all"
            run = self.runs.get(task_id)
            if not run or run["state"] != "running" or run.get("stopping"):
                return
            run["stopping"] = datetime.now().isoformat(timespec="seconds")
            self._save()
            args = (task_id, run["pid"], self.procs.get(task_id), _run_start(run) + SLACK)
        threading.Thread(target=self._stop, args=args, daemon=True).start()

    def _stop(self, task_id: str, pid: int, proc: subprocess.Popen | None, created_by: datetime) -> None:
        def ended() -> bool:
            return proc.poll() is not None if proc else not pid_alive(pid, created_by)

        asked = send_ctrl_break(pid)
        deadline = time.monotonic() + self.stop_grace_s
        while asked and not ended() and time.monotonic() < deadline:
            time.sleep(0.25)
        forced = not ended()
        if forced:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
            if proc:
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    pass
        with self.lock:
            run = self.runs.get(task_id)
            if not run or run.get("pid") != pid:  # a newer run has started meanwhile
                return
            # asked: it ended within the grace time; forced: it did not; killed: it could not be asked
            run["stop"] = "asked" if not forced else "forced" if asked else "killed"
            if run["state"] == "running":
                run.update(
                    state="stopped",
                    finished=datetime.now().isoformat(timespec="seconds"),
                    exit_code=proc.poll() if proc else None,
                )
                self.procs.pop(task_id, None)
            self._save()

    def run_all(self) -> list[str]:
        """Runs, in tasks.yaml order, every task not yet done today; stops at the first one that does not finish
        done. Returns the ids queued."""
        with self.lock:
            if self.queue:
                return list(self.queue)
            self.queue = [t for t in self.tasks if not self._done_today(t)]
            queued = list(self.queue)
        threading.Thread(target=self._drain, daemon=True).start()
        return queued

    def _drain(self) -> None:
        while True:
            with self.lock:
                if not self.queue:
                    return
                task_id = self.queue[0]
            if self.start(task_id):
                break
            while True:
                time.sleep(2)
                with self.lock:
                    self._settle(task_id)
                    state = self.runs[task_id]["state"]
                if state != "running":
                    break
            with self.lock:
                if state != "done" or not self.queue:
                    self.queue.clear()
                    return
                self.queue.pop(0)
        with self.lock:
            self.queue.clear()

    # ----- views -----
    def _done_today(self, task_id: str) -> bool:
        run = self.runs.get(task_id)
        return bool(run and run["state"] == "done" and run["started"][:10] == datetime.now().date().isoformat())

    def log_text(self, task_id: str, lines: int = 300) -> str:
        run = self.runs.get(task_id)
        if not run:
            return ""
        return "\n".join(_tail(self.log_dir / run["log"]).splitlines()[-lines:])

    def reminders(self, previews: dict[str, str], now: datetime | None = None) -> list[dict]:
        """Start of Day reminders due now (reminder.py), for tasks with `remind`; `previews`: each task's preview
        line, for its latest start."""
        now = now or datetime.now(UTC)
        out = []
        with self.lock:
            for task_id, task in self.tasks.items():
                if not task.remind or (task.claim and self._held_elsewhere(task, now)):
                    continue  # the other PC runs today's daily tasks: no nagging here
                self._settle(task_id)
                running = self.runs.get(task_id, {}).get("state") == "running"
                prog = progress.read(task.resolved_progress_file())
                if due := reminder.due(task, now, running, prog, previews.get(task_id, "")):
                    out.append(due)
        return out

    def _progress(self, task: TaskConfig, run: dict, now: datetime) -> dict | None:
        """The task's progress file, seen at `now`, when it is this run's: started while this run was going."""
        p = progress.read(task.resolved_progress_file())
        began = progress.when(p.get("started_utc")) if p else None
        if began is None:
            return None
        end = _aware(run["finished"]) if run.get("finished") else now
        if not _run_start(run) - SLACK <= began <= end:
            return None
        return progress.view(p, now, progress.zone(task.timezone))

    def status(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        out = []
        with self.lock:
            for task_id, task in self.tasks.items():
                self._settle(task_id)
                run = self.runs.get(task_id)
                item = {
                    "id": task_id,
                    "label": task.label,
                    "description": task.description,
                    "summary": task.summary,
                    "when": task.when,
                    "expected_minutes": task.expected_minutes,
                    "has_preview": bool(task.preview_cmd),
                    "done_today": self._done_today(task_id),
                    "again_label": task.again_label,
                    "queued": task_id in self.queue[1:],
                    "run": None,
                }
                if run:
                    text = _tail(self.log_dir / run["log"])
                    steps = PROGRESS.findall(text)
                    lines = [ln for ln in text.splitlines() if ln.strip()]
                    prog = self._progress(task, run, now)
                    item["run"] = {
                        **{k: run[k] for k in ("state", "started", "finished", "exit_code")},
                        "stopping": bool(run.get("stopping")) and run["state"] == "running",
                        "stop": run.get("stop"),  # how a stopped run ended: asked, forced or killed
                        "step": {"k": int(steps[-1][0]), "n": int(steps[-1][1]), "title": steps[-1][2].strip()}
                        if steps
                        else None,
                        "last_line": lines[-1][-300:] if lines else "",
                        "progress": prog,
                    }
                    if prog and prog["step"]:  # the file is newer than the log's last step line
                        item["run"]["step"] = prog["step"]
                out.append(item)
            running_all = bool(self.queue)
        return {"running_all": running_all, "stop_grace_s": self.stop_grace_s, "tasks": out}
