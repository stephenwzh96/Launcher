# Dashboard Launcher

One page (`localhost:9000`) to see, start, and stop the local dashboards.

New here? Start with [`START_HERE.md`](START_HERE.md): the program's status, the day's timetable, the machines
and the reading order. Open work is in [`BACKLOG.md`](BACKLOG.md); dependencies and their expiry in
[`RISKS.md`](RISKS.md).

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
  more entries to `processes`. The app shows Running only when all of them are
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
- **The IBKR cycle's reminder** (team review, 20 Nov 2026, trade operations 4: the day side told nobody when a press
  was forgotten). The cycle has two presses and an approval between them, and leaves no record file until its night
  is over, so its `remind` names IBKR's heartbeat file instead of a `record`:

  ```yaml
    timezone: Australia/Sydney
    remind:
      at: ["15:00", "15:30", "15:50"]
      heartbeat: ../IBKR/logs/heartbeat.json   # IBKR's IBKR_HEARTBEAT_FILE on this PC: change both together
      go: ../Trend/AIJPMT1A_build/data/logs/sod_{t}.json
  ```

  On a weekday from the first `at` time, once Start of Day's record for the trade day's decision date says GO
  (before that, Start of Day's own reminder stands; on a HOLD there is nothing to press), the banner says "IBKR
  paper cycle for Thu 19 Nov: Start of Day is GO, and the first press is not done" while the heartbeat shows no run
  for the trade day's cycle, with a Start button; and "... the list waits for your approval" while that cycle's last
  run ended `waiting`, with no Start button (approve on MTFA Operations first, then press Start trading). No banner
  while the launcher runs a press, while a run for the cycle beats (started here or elsewhere), or once its run ended
  any other way (done, halted: the cycle's own Telegram alert says what to do). The trade day is the task's claim
  day (`claim_day`), so the banner names the cycle a press would run. A missing heartbeat file reads as "first press
  not done". Like Start of Day's, it is a banner while the page is open; the phone hears from the cycle itself
  (waiting, halted, the morning summary).
- **Result**: exit code 0 is Done, anything else Failed.
- **Order**: put a task after the ones it needs; Run all never starts a task after a failure.
- Each run writes `logs/tasks/<id>_<time>.log`; the last run of every task is kept in `logs/tasks_state.json`, so
  "done today" survives a launcher restart. A task left running when the launcher restarted is followed by its pid
  and shows "result unknown" when it ends.
- **One PC per day** (`claim: daily`): MTFA Start of Day and the IBKR paper cycle run on one PC per day. Before the
  first of them starts, the launcher claims the day on GitHub (`refs/daily-claims/daily/<date>` in this repo; only the
  first claim is accepted). The PC holding the claim can re-run its tasks and press the cycle again; the other PC is
  refused ("already started on laptop at 09:41") and offered **Take over**, only for a run that ended or a PC that is
  off. Take over is refused again while the other PC's sync says it ran in the last 15 minutes (it is on) or was
  running a daily task when it last ran; a second, plainer confirmation takes over anyway. The day is Start of Day's
  date in Sydney; the cycle (`claim_day: "18:00 America/New_York"`) claims the trade day it runs, which is the same
  day from its first press until 18:00 New York the next morning (10:00 Sydney from November to March, 08:00 from
  April to October), so a press or restart after midnight does not take the next day. The sync tool not installed
  (`MachineSync\machine.txt`): not started. **GitHub unreachable** (team review, 20 Nov 2026, trade operations 9,
  architect 3: GitHub was a hard dependency of every press): IBKR's run lock refuses a second run of a book in the
  book's own database, whoever starts it. So a PC that is the day's recorded holder (`MachineSync\daily_claim.json`:
  it claimed the day earlier, or its sync saw it hold the day) starts anyway, and the run's row says "Started with:
  GitHub could not be reached (...), so the day's claim was not checked there ...". Any other PC is refused, and the
  page offers **Start without the claim** with a plain warning: only if the other PC is off or is not running the
  day's daily tasks (nothing stops a second Start of Day on the other PC). Starting without the claim records this
  PC as the day's holder in `daily_claim.json` and says so on the row; once GitHub answers again the next press
  claims the day there as usual (a holder already on GitHub is still refused). The reminder is not shown on the PC
  that does not hold the day. See `machine_sync/` and `docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md`.
- **In step before a daily start**: before claiming the day, the launcher checks every repo the task uses (from its
  folder and command line, and the launcher itself): on its default branch (not detached), no Git operation in
  progress, no commits missing from GitHub, not split from it; and the sync updated the task's libraries after their
  last code change (`MachineSync\pending_uv.json` lists none of its repos). Otherwise it refuses and says what
  differs; **Start anyway** (the page asks) starts it regardless. Two things only warn, and the start goes ahead:
  edited or staged tracked files (Start of Day rewrites some of Trend's itself, committed hours later; the day's
  first start records them in the claim), and newer data the other PC's note lists in the daily tasks' repos that is not here yet (up to 5
  files, each with why: "should arrive with the next sync", "laptop last seen 70 min ago", "open or in use here",
  "held deletion (needs --allow-deletes)", "held while a daily task runs here"). The row then says "Started with:
  ...". Untracked files are fine. The claim's commit message lists each repo's commit below its first line (`Trend
  <sha>`, then `+edits: Trend 2 files` when there are edits). That record is the day's first start's: later presses
  (re-runs, the cycle's Start trading) re-use the claim and leave its message as it was; a take-over writes a new one.
  Run all stops at a refused start and the page shows that refusal, with its offer, as for a single start.

## How it works

- `config.py` — loads and validates `apps.yaml` and `tasks.yaml`.
- `process_control.py` — start/stop a process, check if it's up (TCP or
  HTTP), find a process by the port it's listening on, whether a pid is
  still running, and CTRL_BREAK to a task (through `ctrl_break.py`).
- `task_runner.py` — runs the Start of Day tasks: start, stop (asked, then
  forced), Run all, progress from the log, last run per task.
- `progress.py` — reads a task's progress file: step, last output, ETA, stalled
  or abandoned.
- `reminder.py` — whether a task's reminder is due: Start of Day's (a record for the day), and the IBKR cycle's two
  presses (its heartbeat, after Start of Day's GO).
- `app.py` — thin FastAPI layer: `/api/apps`, `/api/status`,
  `/api/start/{id}`, `/api/stop/{id}`; `/api/tasks`, `/api/tasks/run-all`,
  `/api/tasks/{id}/start|stop|log|preview`; `/api/tasks` also lists the
  reminders due and whose day it is; `/api/day/reserve[?day=YYYY-MM-DD]` is "Run today here" (or a later day).
  Serves `static/index.html` at `/`. On the PC a task's `auto` names (tasks.yaml), once `MachineSync\auto_start.on`
  exists there, it starts that task by itself when due (`task_runner.auto_tick`, every minute).
- `static/index.html` — fetches `/api/apps` once to build the cards, then
  polls `/api/status` every 3s. No app-specific code in here.

Stopping looks up *whatever process is currently listening on the configured
port* rather than remembering what it started — so Stop still works even if
you started something manually, or the launcher itself restarted.

## Machine sync (desktop, laptop and VPS)

`machine_sync/` keeps the desktop, the laptop and the VPS on the same code and data, so work and the daily run can
continue on any of them. Design: `docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md` (two PCs) and
`docs/superpowers/specs/2026-11-20-three-machine-design.md` (the VPS as the third, and the default holder of the
day). Each PC has one outbox (laptop `TripSync`, desktop `DesktopSync`, VPS `VpsSync`), shared with the other two:
an outbox holds that PC's own changes until every other PC has them (and another PC's versions once that PC has been
quiet for 6 hours). A PC that has never written a note (the VPS, until it is installed) is not waited for.

- **What it does, every 5 minutes and at logon, unlock and wake** (Task Scheduler task "Machine sync"):
  - code: fetches the 8 repos, fast-forwards every branch, and follows the branch and commit of the PC last worked on
    (in Trend, IBKR and the launcher only on their default branch: a daily run never starts on a feature branch it
    followed). It never commits, pushes, merges or forces; a repo with edits, unpushed commits or a daily task running
    is left as it is and the status says why. Unpushed commits stay on their PC: push them to share.
  - data: Git-ignored data files move both ways through Syncthing (laptop `C:\Users\User\TripSync`, desktop
    `C:\Users\User\DesktopSync`, Tailscale only). The newer change wins on both PCs (newer by the versions' history,
    so a clock that is off does not decide; the status warns when the two clocks differ by more than 30 s); a file
    changed on both, and every deletion, is kept in `C:\Users\User\MachineSync\backup\<date>` for 60 days.
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

- **Install on a PC** (from this folder): `& $py -m machine_sync install --machine desktop` (or `laptop`, or
  `vps`; on the VPS the user folder is `C:\Users\Administrator`). The installed copy updates itself from this repo's
  `origin/main` after passing a self-test (every module imports, and a dry run on three made-up PCs in a temporary
  folder gives the right answers). It does not update while a daily task
  runs on that PC (started from the launcher or a terminal); the status says an update waits.
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

The trade-day rule's copies (`task_runner.claim_day` for the IBKR cycle, `reminder.decision_date`) are tested against
IBKR's `reference/trade_day_cases.json` (`tests/test_trade_day_cases.py`); `tests/trade_day_cases.json` is this repo's
copy, for CI and a checkout without IBKR beside it, and a test fails when it differs from IBKR's. When IBKR's table
changes, copy it over.

CI (`.github/workflows/ci.yml`, team review developer 3): every push runs `python -m unittest discover tests` on
Windows from `requirements.lock.txt`.

The sync tool's tests also run on the standalone Python:
`& $py -m unittest discover -s tests -p "test_*.py" -t tests` (the four launcher test files then fail to import).

To try the page against made-up tasks and progress files, point the launcher at
another tasks file and logs folder, so the real task state is never touched:

```powershell
$env:LAUNCHER_TASKS = "$env:TEMP\launcher-test\tasks.yaml"
$env:LAUNCHER_LOGS = "$env:TEMP\launcher-test\logs"
.venv\Scripts\python.exe -m uvicorn app:app --port 9010
```
