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
  timezone: Australia/Sydney  # optional: the clock of the progress file's local times and the reminder; default this machine's
  remind:                   # optional: see "Reminder" below
    at: ["11:00", "12:30"]
    record: MyProject/logs/day_{t}.json
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
- **Reminder** (optional, `remind`): on a weekday in the task's `timezone`, from the first `at` time, a banner at the
  top of the page says "<label> for <t> not started; latest start HH:MM" while all of these hold: no `record` file
  for today's decision date t (`{t}` is t as YYYY-MM-DD: the weekday before today, Monday's is Friday), the launcher
  is not running the task, and the progress file shows no live run for t. The latest start comes from the task's
  preview line when it says "start by HH:MM", and is left out otherwise. The banner has a Start button; Dismiss hides
  it until the next `at` time, when it comes back in red. The tab title changes too. It is only a reminder while the
  page is open (no Windows notification, no scheduled task): MTFA Start of Day reminds at 11:00 and 12:30 Sydney
  and is still started by hand (Trend DECISIONS 2026-10-27).
- **Result**: exit code 0 is Done, anything else Failed.
- **Order**: put a task after the ones it needs; Run all never starts a task after a failure.
- Each run writes `logs/tasks/<id>_<time>.log`; the last run of every task is kept in `logs/tasks_state.json`, so
  "done today" survives a launcher restart. A task left running when the launcher restarted is followed by its pid
  and shows "result unknown" when it ends.
- **One PC per day** (`claim: daily`): MTFA Start of Day and the IBKR paper cycle run on one PC per day. Before the
  first of them starts, the launcher claims the day on GitHub (`refs/daily-claims/daily/<date>` in this repo; only
  the first claim is accepted). The PC holding the claim can re-run its tasks and press the cycle again; the other PC
  is refused ("already started on laptop at 09:41") and offered **Take over**, only for a run that ended or a PC that
  is off. The day is Start of Day's date in Sydney; the cycle (`claim_day: "18:00 America/New_York"`) claims the trade
  day it runs, which is the same day from its first press until 18:00 New York the next morning (10:00 Sydney from
  November to March, 08:00 from April to October), so a press or restart after midnight does not take the next day. GitHub unreachable or the sync tool not installed (`MachineSync\machine.txt`): not started. The reminder is
  not shown on the PC that does not hold the day. See `machine_sync/` and
  `docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md`.

## How it works

- `config.py` — loads and validates `apps.yaml` and `tasks.yaml`.
- `process_control.py` — start/stop a process, check if it's up (TCP or
  HTTP), find a process by the port it's listening on, whether a pid is
  still running, and CTRL_BREAK to a task (through `ctrl_break.py`).
- `task_runner.py` — runs the Start of Day tasks: start, stop (asked, then
  forced), Run all, progress from the log, last run per task.
- `progress.py` — reads a task's progress file: step, last output, ETA, stalled
  or abandoned.
- `reminder.py` — whether a task's Start of Day reminder is due.
- `app.py` — thin FastAPI layer: `/api/apps`, `/api/status`,
  `/api/start/{id}`, `/api/stop/{id}`; `/api/tasks`, `/api/tasks/run-all`,
  `/api/tasks/{id}/start|stop|log|preview`; `/api/tasks` also lists the
  reminders due. Serves `static/index.html` at `/`.
- `static/index.html` — fetches `/api/apps` once to build the cards, then
  polls `/api/status` every 3s. No app-specific code in here.

Stopping looks up *whatever process is currently listening on the configured
port* rather than remembering what it started — so Stop still works even if
you started something manually, or the launcher itself restarted.

## Machine sync (desktop and laptop)

`machine_sync/` keeps the desktop and the laptop on the same code and data, both ways, so work can continue on
either PC. Design: `docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md`.

- **What it does, every 5 minutes and at logon, unlock and wake** (Task Scheduler task "Machine sync"):
  - code: fetches the 8 repos, fast-forwards every branch, and follows the branch and commit of the PC last worked
    on. It never commits, pushes, merges or forces; a repo with edits, unpushed commits or a daily task running is
    left as it is and the status says why. Unpushed commits stay on their PC: push them to share.
  - data: Git-ignored data files move both ways through Syncthing (laptop `C:\Users\User\TripSync`, desktop
    `C:\Users\User\DesktopSync`, Tailscale only). The newer change wins on both PCs (newer by the versions' history, so a clock that is off
    does not decide; the status warns when the two clocks differ by more than 30 s); a file changed on both, and
    every deletion, is kept in `C:\Users\User\MachineSync\backup\<date>` for 60 days.
  - trading safety: while a daily task runs (started from the launcher or from a terminal), nothing in Trend or
    IBKR changes on that PC; on the PC that holds the day's claim, their code stays fixed until 09:00 the next day.
- **Status:** `C:\Users\User\MachineSync\sync_status.txt` (log: `sync.log`). It names the other PC's last run,
  today's claim, each repo's state and the data moved.
- **Commands** (standalone Python, from `C:\Users\User\MachineSync\tool`):

```powershell
$py = "C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
& $py -I C:\Users\User\MachineSync\tool\run_sync.py run                   # one run now
& $py -I C:\Users\User\MachineSync\tool\run_sync.py run --update-frozen   # also update code kept for today's run
& $py -I C:\Users\User\MachineSync\tool\run_sync.py run --allow-deletes   # let a held batch of deletions through
& $py -I C:\Users\User\MachineSync\tool\run_sync.py status
```

- **Install on a PC** (from this folder): `& $py -m machine_sync install --machine desktop` (or `laptop`). The
  installed copy updates itself from this repo's `origin/main` after passing a self-test (every module imports, and
  a dry run on two made-up PCs in a temporary folder gives the right answers). It does not update while a daily task
  runs on that PC, nor on the PC holding today's claim until 09:00 the next day (`run --update-frozen` lets it); the
  status says an update waits.
- **Roll back an update:** the copy it replaced stays in `C:\Users\User\MachineSync\tool.old` until the next update.
  1. Create `C:\Users\User\MachineSync\hold_update.txt` (any content): no update is installed while it exists, so
     the tool does not reinstall the bad `main` 5 minutes later.
  2. Between two runs (the status's time; a run takes seconds), rename `MachineSync\tool` to `tool.bad` and
     `tool.old` to `tool`. Check with `& $py -I C:\Users\User\MachineSync\tool\run_sync.py run`.
  3. Once `main` is fixed, delete `hold_update.txt`: the next run installs it.

## Testing

```powershell
.venv\Scripts\python.exe -m unittest discover tests
```

The sync tool's tests also run on the standalone Python:
`& $py -m unittest discover -s tests -p "test_*.py" -t tests` (the four launcher test files then fail to import).

To try the page against made-up tasks and progress files, point the launcher at
another tasks file and logs folder, so the real task state is never touched:

```powershell
$env:LAUNCHER_TASKS = "$env:TEMP\launcher-test\tasks.yaml"
$env:LAUNCHER_LOGS = "$env:TEMP\launcher-test\logs"
.venv\Scripts\python.exe -m uvicorn app:app --port 9010
```
