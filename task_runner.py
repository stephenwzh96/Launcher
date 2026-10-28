"""Running the one-shot Start of Day tasks in tasks.yaml: start, stop, progress, and "done today".

Unlike apps, a task ends. Each run writes its own log (logs/tasks/<id>_<time>.log), and the last run of every task
is kept in logs/tasks_state.json, so "done today" and the last result survive a launcher restart. Progress comes
from the log: the latest line containing "== k/n Title".
"""
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from config import TaskConfig

PROGRESS = re.compile(r"== (\d+)/(\d+) (.+)")
TAIL_BYTES = 64_000


def _pid_alive(pid: int) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True).stdout
    return str(pid) in out


def _tail(path: Path, max_bytes: int = TAIL_BYTES) -> str:
    try:
        with open(path, "rb") as f:
            f.seek(max(0, path.stat().st_size - max_bytes))
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


class TaskRunner:
    def __init__(self, tasks: list[TaskConfig], log_dir: Path):
        self.tasks = {t.id: t for t in tasks}
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
        """Turn a finished process into done/failed. A run whose process this launcher did not start (it was
        restarted mid-run) is followed by its pid; when that ends the result is unknown."""
        run = self.runs.get(task_id)
        if not run or run["state"] != "running":
            return
        proc = self.procs.get(task_id)
        if proc is not None:
            code = proc.poll()
            if code is None:
                return
            run.update(state="done" if code == 0 else "failed", exit_code=code)
            self.procs.pop(task_id)
        elif _pid_alive(run["pid"]):
            return
        else:
            run.update(state="unknown")
        run["finished"] = datetime.now().isoformat(timespec="seconds")
        self._save()

    # ----- actions -----
    def start(self, task_id: str) -> str | None:
        """Starts the task unless it is already running. Returns an error message on failure, else None."""
        task = self.tasks[task_id]
        with self.lock:
            self._settle(task_id)
            if self.runs.get(task_id, {}).get("state") == "running":
                return f"{task.label} is already running"
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
                        creationflags=subprocess.CREATE_NO_WINDOW,
                        env=env,
                    )
            except OSError as e:
                return f"{task.label}: failed to start ({e})"
            self.procs[task_id] = proc
            self.runs[task_id] = {
                "state": "running",
                "started": now.isoformat(timespec="seconds"),
                "finished": None,
                "exit_code": None,
                "pid": proc.pid,
                "log": log_path.name,
            }
            self._save()
        return None

    def stop(self, task_id: str) -> None:
        with self.lock:
            self.queue.clear()  # stopping one task also ends a "Run all"
            run = self.runs.get(task_id)
            if not run or run["state"] != "running":
                return
            subprocess.run(["taskkill", "/PID", str(run["pid"]), "/T", "/F"], capture_output=True)
            self.procs.pop(task_id, None)
            run.update(state="stopped", finished=datetime.now().isoformat(timespec="seconds"))
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

    def status(self) -> dict:
        out = []
        with self.lock:
            for task_id, task in self.tasks.items():
                self._settle(task_id)
                run = self.runs.get(task_id)
                item = {
                    "id": task_id,
                    "label": task.label,
                    "description": task.description,
                    "expected_minutes": task.expected_minutes,
                    "has_preview": bool(task.preview_cmd),
                    "done_today": self._done_today(task_id),
                    "queued": task_id in self.queue[1:],
                    "run": None,
                }
                if run:
                    text = _tail(self.log_dir / run["log"])
                    steps = PROGRESS.findall(text)
                    lines = [ln for ln in text.splitlines() if ln.strip()]
                    item["run"] = {
                        **{k: run[k] for k in ("state", "started", "finished", "exit_code")},
                        "step": {"k": int(steps[-1][0]), "n": int(steps[-1][1]), "title": steps[-1][2].strip()}
                        if steps
                        else None,
                        "last_line": lines[-1][-300:] if lines else "",
                    }
                out.append(item)
            running_all = bool(self.queue)
        return {"running_all": running_all, "tasks": out}
