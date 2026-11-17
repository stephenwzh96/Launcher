# Dashboard Launcher

One page (`localhost:9000`) to see, start, and stop the local dashboards.

## Run it

```powershell
.\run.ps1
```

## Adding a new app

Edit [`apps.yaml`](apps.yaml) — nothing else needs to change. No Python or
HTML edits, the page and API both read this file.

```yaml
- id: my-app          # used internally, keep it short and unique
  label: My App        # shown on the card
  open_port: 3000       # port the "Open" link jumps to
  processes:
    - cwd: MyApp         # folder, relative to Marco/
      cmd: ["MyApp/.venv/Scripts/python.exe", "-m", "uvicorn", "app:app", "--port", "3000"]
      port: 3000          # port the status check watches
      log: my-app.log      # written to launcher/logs/
```

- **Multiple processes per app** (like CB Pricer's backend + frontend): add
  more entries to `processes`. The card goes green only when all of them are
  up, and Start/Stop act on all of them together.
- **`health: http`** (default is `tcp`): use this instead of the plain port
  check for anything that accepts a connection before it's actually ready to
  serve — set `health_path` too if it's not `/`.
- **`env`**: a dict of extra environment variables for that process, if it
  needs config passed in rather than read from a file.
- Paths in `cwd` and any `cmd` token containing a slash are resolved relative
  to `Marco/` (the folder above this one). Bare tokens like `npm.cmd` are
  looked up on PATH as usual.

## Start of Day tasks

The **Start of Day** panel at the top lists one-shot jobs to start by hand each morning (nothing runs on a
schedule). Each row shows Not run yet / Running k/n step / Done today / Failed at step, with Start (Rerun once done
today), Stop and Log. **Run all** runs every task not yet done today, top to bottom, and stops at the first failure.

**Stop asks first.** Each task runs in its own process group (`CREATE_NEW_PROCESS_GROUP`, no window). Stop sends
that group `CTRL_BREAK_EVENT` (Python sees `SIGBREAK`), so the task can record why it ended: Trend's Start of Day
records `stopped` and a FAILED day. The row shows "Stopping" meanwhile. If the task has not ended 20 s later it is
ended by force (`taskkill /T /F`), and the row says "Stopped by force". Since the task has its own hidden console,
the event is sent by a small helper, [`ctrl_break.py`](ctrl_break.py), that attaches to that console.

Add a task to [`tasks.yaml`](tasks.yaml); nothing else changes:

```yaml
- id: my-task              # short and unique
  label: My task            # shown on the row
  description: What it does and when to start it.
  cwd: MyProject             # relative to Marco/, like apps.yaml
  cmd: ["MyProject/.venv/Scripts/python.exe", "MyProject/tools/my_task.py"]
  expected_minutes: 5       # optional, shown while it runs
  preview_cmd: ["MyProject/.venv/Scripts/python.exe", "plan.py"]  # optional: its last output line (what today's run will do) is shown under the task
  progress_file: MyProject/logs/progress.json  # optional: see "Progress file" below
  timezone: Australia/Sydney  # optional: the clock of the progress file's local times; default this machine's
  env: {}                   # optional extra environment variables
```

- **Progress**: print a line containing `== k/n Title` before each of the task's n steps (a log timestamp in front
  is fine). Without such lines the row still shows running, done or failed.
- **Progress file** (optional, `progress_file`): a JSON file the task rewrites at each step start, at least every
  15 s while a step prints output, and at the end, in Trend's `sod_progress/1` schema (fields in
  [`progress.py`](progress.py)). The row then shows step k of n, the time since the last output and the ETA (in
  place of `expected_minutes`), and:
  - **Stalled** (red): the file says running and its last output is over 10 minutes old.
  - **Abandoned** (red): the file says running but its process (`pid`) is gone, killed or lost in a restart.
  - A warning when the ETA is after the file's `deliver_by_local` (or the run is still going past it), and when
    the machine is on battery.
  A file is taken as this run's only if it started while this run was going, so yesterday's file is never shown.
- **Result**: exit code 0 is Done, anything else Failed.
- **Order**: put a task after the ones it needs; Run all never starts a task after a failure.
- Each run writes `logs/tasks/<id>_<time>.log`; the last run of every task is kept in `logs/tasks_state.json`, so
  "done today" survives a launcher restart. A task left running when the launcher restarted is followed by its pid
  and shows "result unknown" when it ends.

## How it works

- `config.py` — loads and validates `apps.yaml` and `tasks.yaml`.
- `process_control.py` — start/stop a process, check if it's up (TCP or
  HTTP), find a process by the port it's listening on, whether a pid is
  still running, and CTRL_BREAK to a task (through `ctrl_break.py`).
- `task_runner.py` — runs the Start of Day tasks: start, stop (asked, then
  forced), Run all, progress from the log, last run per task.
- `progress.py` — reads a task's progress file: step, last output, ETA, stalled
  or abandoned.
- `app.py` — thin FastAPI layer: `/api/apps`, `/api/status`,
  `/api/start/{id}`, `/api/stop/{id}`; `/api/tasks`, `/api/tasks/run-all`,
  `/api/tasks/{id}/start|stop|log`. Serves `static/index.html` at `/`.
- `static/index.html` — fetches `/api/apps` once to build the cards, then
  polls `/api/status` every 3s. No app-specific code in here.

Stopping looks up *whatever process is currently listening on the configured
port* rather than remembering what it started — so Stop still works even if
you started something manually, or the launcher itself restarted.

## Testing

```powershell
.venv\Scripts\python.exe -m unittest discover tests
```

To try the page against made-up tasks and progress files, point the launcher at
another tasks file and logs folder, so the real task state is never touched:

```powershell
$env:LAUNCHER_TASKS = "$env:TEMP\launcher-test\tasks.yaml"
$env:LAUNCHER_LOGS = "$env:TEMP\launcher-test\logs"
.venv\Scripts\python.exe -m uvicorn app:app --port 9010
```
