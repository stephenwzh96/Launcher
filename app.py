"""Local launcher: start/stop/status for the dashboards listed in apps.yaml, and the Start of Day tasks in
tasks.yaml.

For a test, LAUNCHER_TASKS names another tasks file and LAUNCHER_LOGS another logs folder (both default to this
folder's), so a trial run never touches the real task state."""
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from config import check_paths, load_apps, load_tasks
from process_control import is_up, start_process, stop_process
from task_runner import TaskRunner

HERE = Path(__file__).resolve().parent
LOG_DIR = Path(os.environ.get("LAUNCHER_LOGS") or HERE / "logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

APPS = {a.id: a for a in load_apps(HERE / "apps.yaml")}
TASKS = load_tasks(Path(os.environ.get("LAUNCHER_TASKS") or HERE / "tasks.yaml"))
RUNNER = TaskRunner(TASKS, LOG_DIR)

for warning in check_paths(list(APPS.values()), TASKS):
    print(f"[launcher] WARNING: {warning}")

app = FastAPI()


@app.middleware("http")
async def no_cache(request, call_next):
    """Always revalidate, so the browser never shows a stale page after the launcher is updated."""
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


def _get_app(app_id: str):
    if app_id not in APPS:
        raise HTTPException(status_code=404, detail=f"unknown app '{app_id}'")
    return APPS[app_id]


@app.get("/api/apps")
def list_apps():
    return [{"id": a.id, "label": a.label, "group": a.group} for a in APPS.values()]


@app.get("/api/status")
def status():
    out = {}
    for app_id, cfg in APPS.items():
        states = [is_up(p) for p in cfg.processes]
        state = "up" if all(states) else "partial" if any(states) else "down"
        out[app_id] = {"label": cfg.label, "state": state, "open_port": cfg.open_port}
    return out


@app.post("/api/start/{app_id}")
def start(app_id: str):
    errors = [err for proc in _get_app(app_id).processes
              if (err := start_process(proc, LOG_DIR))]
    return {"ok": not errors, "errors": errors}


@app.post("/api/stop/{app_id}")
def stop(app_id: str):
    for proc in _get_app(app_id).processes:
        stop_process(proc)
    return {"ok": True}


def _get_task(task_id: str) -> str:
    if task_id not in RUNNER.tasks:
        raise HTTPException(status_code=404, detail=f"unknown task '{task_id}'")
    return task_id


@app.get("/api/tasks")
def task_status():
    """Every task's state, and the Start of Day reminders due now (tasks.yaml `remind`), with the latest start from
    today's preview line."""
    today = datetime.now().date()
    previews = {
        task_id: answer["text"]
        for task_id, (at, answer) in list(_previews.items())
        if answer["ok"] and datetime.fromtimestamp(at).date() == today
    }
    return {**RUNNER.status(), "reminders": RUNNER.reminders(previews)}


@app.post("/api/tasks/run-all")
def run_all_tasks():
    return {"ok": True, "queued": RUNNER.run_all()}


@app.post("/api/tasks/{task_id}/start")
def start_task(task_id: str, take_over: bool = False, allow_unsynced: bool = False, force_take_over: bool = False):
    """Starts a task. A refused daily task (tasks.yaml `claim`) says what the page may offer next (`offer`):
    "take_over" when another PC already started today (`claimed_by`; then take_over=true), "start_anyway" when this
    PC is not in step (then allow_unsynced=true), "take_over_anyway" when the other PC may still be running (then
    force_take_over=true as well)."""
    err = RUNNER.start(_get_task(task_id), take_over=take_over, allow_unsynced=allow_unsynced,
                       force_take_over=force_take_over)
    return {"ok": err is None, "errors": [err] if err else [],
            "claimed_by": RUNNER.refusals.get(task_id) if err else None,
            "offer": RUNNER.offers.get(task_id) if err else None}


@app.post("/api/tasks/{task_id}/stop")
def stop_task(task_id: str):
    RUNNER.stop(_get_task(task_id))
    return {"ok": True}


PREVIEW_TTL_S, PREVIEW_TIMEOUT_S = 600, 90
_previews: dict[str, tuple[float, dict]] = {}  # task id -> (time, answer); a preview is re-run after 10 minutes


@app.get("/api/tasks/{task_id}/preview")
def task_preview(task_id: str, fresh: bool = False):
    """What today's run of a task will do: the last output line of its `preview_cmd` (tasks.yaml)."""
    task = RUNNER.tasks[_get_task(task_id)]
    cmd = task.resolved_preview_cmd()
    if not cmd:
        return {"ok": True, "text": ""}
    hit = _previews.get(task_id)
    if hit and not fresh and time.time() - hit[0] < PREVIEW_TTL_S:
        return hit[1]
    try:
        done = subprocess.run(
            cmd, cwd=task.resolved_cwd(), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=PREVIEW_TIMEOUT_S, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        lines = [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]
        out = (
            {"ok": True, "text": lines[-1]} if done.returncode == 0 and lines
            else {"ok": False, "text": f"Could not check today's plan (exit {done.returncode})."}
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        out = {"ok": False, "text": f"Could not check today's plan: {type(e).__name__}."}
    _previews[task_id] = (time.time(), out)
    return out


@app.get("/api/tasks/{task_id}/log", response_class=PlainTextResponse)
def task_log(task_id: str):
    return RUNNER.log_text(_get_task(task_id))


app.mount("/", StaticFiles(directory=str(HERE / "static"), html=True), name="static")
