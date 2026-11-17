# Two-way machine sync and one daily run per day: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the desktop and laptop on the same code and data within minutes, both ways, and let each daily task
run on one PC per day.

**Architecture:** A standard-library Python package `machine_sync` in the launcher repo, installed to
`C:\Users\User\MachineSync\tool` and run every 5 minutes by Task Scheduler. Code moves through GitHub (fetch,
fast-forward, follow the other PC's branch). Data moves through one Syncthing outbox per PC, with full manifests
and newest-change-wins. The launcher claims each day on GitHub (`refs/daily-claims/...`) before a daily task starts.

**Tech Stack:** Python 3.12 standard library (tool), unittest, Git 2.52, PowerShell (process list, task
registration), FastAPI launcher (existing).

**Spec:** `docs/superpowers/specs/2026-11-17-two-way-machine-sync-design.md`

## Global Constraints

- Tool: standard library only; runs on `C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe` (3.12.10).
- No `zoneinfo`: both PCs run on Sydney local time; use `datetime.now()` local for day and 09:00 freeze boundaries.
- Every path the tool touches comes from a `Settings(home, machine, repos, plain_roots)` object so tests run two
  PCs in temp folders. Real defaults: home `C:\Users\User`, repos `Marco/Australia-Rates, Marco/CB Pricer,
  Marco/Curve, Marco/FOMC, Marco/launcher, IBKR, Trend, FXMGT/JPMQFX01_build`, plain roots `{"FXMGT":
  ["JPMQFX01_build"]}`.
- Outboxes: laptop `<home>\TripSync`, desktop `<home>\DesktopSync`; note at `<outbox>\_state\<machine>.json`.
- State, status, log, backups: `<home>\MachineSync\` (`state.json`, `sync_status.txt`, `sync.log`,
  `backup\<YYYY-MM-DD>\<path>`, `machine.txt`, `daily_claim.json`, `tasks.json`).
- The tool never commits, pushes code, merges, rebases or forces a branch. Its Git moves set
  `GIT_REFLOG_ACTION=machine-sync`.
- Values: interval 5 min; stable file age 60 s; deletion brake max(50, 2% of data files); tombstones 30 days;
  backups 14 days; claims kept 30 days; code freeze until 09:00 local the next day; note `format: 1`.
- Launcher tests run as `.venv\Scripts\python.exe -m unittest discover tests` from `Marco\launcher`; tool tests also
  run under the standalone Python.

## Review Focus

- A file that reverts to an earlier content (restore, rerun with identical output) must still win on the other PC
  (test `test_revert_to_earlier_content_propagates`, Task 3).
- Both PCs changing the same file before either syncs: the newer wins on both, the older is backed up on the PC that
  lost it, and both statuses list it (`test_clash_backs_up_loser_and_converges`, Task 3).
- Both PCs coming online with no history (first run after install): the newer copy by modified time wins, not the PC
  that ran first (`test_bootstrap_keeps_newer_mtime`, Task 3).
- The leading PC's branch deleted on GitHub after a merge: neither PC gets stuck (`test_gone_branch_falls_back`,
  Task 2).
- Two PCs claiming the same day at once: exactly one wins (`test_second_claim_refused`, Task 5).

---

### Task 1: Settings, Git helper and repo state

**Files:**
- Create: `machine_sync/__init__.py`, `machine_sync/settings.py`, `machine_sync/gitops.py`
- Test: `tests/machine_sync/__init__.py`, `tests/machine_sync/helpers.py`, `tests/machine_sync/test_gitops.py`

**Interfaces:**
- Produces: `NOTE_FORMAT = 1`; `Settings(home: Path, machine: str, repos: list[str], plain_roots: dict[str,
  list[str]])` with properties `peer`, `sync_dir`, `outbox(machine)`, `own_outbox`, `peer_outbox`, `note_path(machine)`
  and `Settings.real(machine)`.
- Produces: `git(repo: Path, *args, check=False) -> CompletedProcess` (UTF-8, no window, `GIT_REFLOG_ACTION`);
  `RepoState` dataclass: `branch: str | None, head: str, upstream: str | None, upstream_gone: bool, upstream_head:
  str | None, unpushed: int, uncommitted: int, operation: str | None, last_activity: float`;
  `read_repo(repo: Path) -> RepoState`.
- Produces (tests): `helpers.make_origin(tmp) -> Path` (bare repo with `main` and one commit), `helpers.clone(origin,
  dest) -> Path`, `helpers.commit(repo, name, text) -> str`, `helpers.two_pcs(tmp, repos) -> (Settings, Settings)`
  (desktop and laptop homes sharing bare origins), `helpers.syncthing(src: Settings, dst: Settings)` (mirror
  `src.own_outbox` to the same folder under `dst.home`, deletions included).

- [ ] **Step 1: Tests** `test_read_repo_clean_main` (branch `main`, unpushed 0, uncommitted 0, operation None);
  `test_unpushed_and_uncommitted_counted` (one local commit → unpushed 1; one edited tracked file + one untracked
  not-ignored file → uncommitted 2; an ignored file → not counted); `test_gone_upstream` (delete the branch on the
  origin, fetch --prune → `upstream_gone` True, `unpushed` 0); `test_last_activity_ignores_tool_moves` (a
  `git merge --ff-only` run through `git()` does not change `last_activity`; a user `git commit` does).
- [ ] **Step 2:** run `python -m unittest tests.machine_sync.test_gitops -v` → fails (module missing).
- [ ] **Step 3:** implement. Unpushed = `rev-list --count @{u}..HEAD` when upstream exists and is not gone, else 0.
  Last activity = newest `git reflog show --date=unix HEAD` entry whose message does not start with
  `machine-sync`, or the newest modified time of an uncommitted file if later. Operation from `.git` markers
  (`rebase-merge`, `rebase-apply`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`, `BISECT_LOG`).
- [ ] **Step 4:** run → pass.
- [ ] **Step 5:** commit "machine_sync: settings, Git helper and repo state".

### Task 2: Code step

**Files:**
- Create: `machine_sync/code_sync.py`
- Test: `tests/machine_sync/test_code_sync.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `repo_note(state: RepoState, busy_running: bool) -> dict` (the per-repo part of a note);
  `sync_code(cfg: Settings, repo: str, peer: dict | None, frozen: bool, running: bool) -> RepoResult` with
  `RepoResult(repo, line: str, moved: bool, before: str, after: str, warnings: list[str])`;
  `ff_other_branches(repo_path) -> list[str]`; `after_move(cfg, repo, before, after, in_use: set[Path]) ->
  list[str]` (uv sync / npm / restart lines).

- [ ] **Step 1: Tests** (two clones of one bare origin, "desktop" and "laptop"):
  `test_follows_peer_branch_when_idle` (laptop creates and pushes `feature`; desktop idle on `main` with an older
  activity → desktop on `feature` at the same commit); `test_stays_when_working_here` (desktop has an edited file →
  stays on `main`, line says edits); `test_peer_unpushed_goes_to_last_pushed` (laptop pushed A then committed B
  unpushed → desktop at A, line says "1 unpushed"); `test_never_moves_local_only_commits` (desktop local branch
  `feature` has a commit GitHub lacks, peer leads on `feature` → no move, flagged);
  `test_fast_forwards_non_checked_out_branches`; `test_gone_branch_falls_back` (laptop on `claude/x`, branch
  deleted on origin after merge into `main` → laptop idle moves to `main` keeping local `claude/x`; desktop
  following a gone branch fast-forwards its own instead); `test_frozen_does_not_move`; `test_split_branch_flagged`
  (desktop's `main` has a commit and origin `main` has another → no move, "merge by hand");
  `test_ignored_files_survive_checkout` (an ignored data file in the working copy is untouched by a branch move).
- [ ] **Step 2:** run → fail.
- [ ] **Step 3:** implement `sync_code` exactly as spec "Code step" 1–6. Leader = peer when
  `peer["last_activity"] > local.last_activity` and `peer["head"] != local.head`. Branch moves: `git switch
  --no-overwrite-ignore <branch>` then `git merge --ff-only <target>` when the local branch is an ancestor of the
  target, `git switch --no-overwrite-ignore -c <branch> --track origin/<branch>` then `git reset --keep <target>`
  when missing; never `-C`/`--force`. Default branch = `git symbolic-ref refs/remotes/origin/HEAD` (fallback
  `main`, then `master`).
- [ ] **Step 4:** run → pass.
- [ ] **Step 5:** commit "machine_sync: code step follows the PC last worked on".

### Task 3: Data versions, import and outbox

**Files:**
- Create: `machine_sync/data_files.py` (what is data, hash cache), `machine_sync/data_sync.py`
- Test: `tests/machine_sync/test_data_sync.py`

**Interfaces:**
- Consumes: Task 1.
- Produces: `data_files(cfg: Settings) -> dict[str, Path]` (relative POSIX path → absolute path);
  `scan(cfg, state: dict, now: float) -> dict` (updated state); `import_from_peer(cfg, state, peer_note: dict,
  frozen_repos: set[str], allow_deletes: bool, now: float) -> ImportResult` with `ImportResult(taken: int, deleted:
  int, waiting: int, skipped: list[str], clashes: list[str], held_deletes: int)`; `refresh_outbox(cfg, state,
  peer_note: dict | None) -> int`; `files_for_note(state) -> dict`; `load_state(cfg) -> dict`;
  `save_state(cfg, state)`.
- Version entry in state: `{"h": hex16 | None, "t": float, "m": machine, "b": float | None, "del": bool, "size":
  int, "mt": int}`; in a note: `[h, t, m, b, del]`. Order of versions: `(t, m)`.

- [ ] **Step 1: Tests** (two homes, one shared "repo" whose `.gitignore` ignores `data/`, Syncthing simulated with
  `helpers.syncthing`, a fake clock): `test_new_file_reaches_other_pc`; `test_change_reaches_other_pc`;
  `test_no_bounce_back` (after desktop takes laptop's file, desktop's outbox stays empty and laptop's outbox copy
  is removed once desktop's note shows it); `test_revert_to_earlier_content_propagates` (v1 → v2 on desktop,
  laptop takes v2, laptop writes v1 again → desktop ends with v1); `test_clash_backs_up_loser_and_converges` (both
  change before a sync; later stamp wins on both; loser copy under `MachineSync/backup/<date>/`; clash listed);
  `test_deletion_propagates_with_backup`; `test_deletion_brake_holds_mass_delete` (60 of 100 files deleted →
  held, flagged; with `allow_deletes=True` → done); `test_bootstrap_keeps_newer_mtime` (no state on either PC, same
  path differs, laptop copy has the newer mtime, desktop runs first → both end with laptop's);
  `test_waits_for_content` (note arrives before the file → `waiting` 1, nothing replaced);
  `test_tracked_here_not_imported`; `test_frozen_repo_not_imported`; `test_unstable_file_not_exported` (modified
  < 60 s ago); `test_sqlite_moves_only_without_wal` (a `-wal` next to it on either side blocks; `-wal` never
  synced); `test_excluded_files` (`PG_VERSION` folder, `*.lock`, `.env`, `node_modules/`, `logs/` never in
  `data_files`); `test_reappearing_path_after_tombstone_is_new_change`.
- [ ] **Step 2:** run → fail.
- [ ] **Step 3:** implement per spec "Data step". Hash: SHA-256 first 16 hex chars, cached by `(size, mtime_ns)`.
  Scan stamps: first sight with no history → file mtime; a change to a known path or a path with a tombstone → `now`.
  Clash = the replaced local version's `t` is later than the incoming version's `b` (the incoming PC never saw it).
  Import writes atomically (`.msync-tmp` then `os.replace`) and copies the incoming mtime. Outbox rule: for each
  non-deleted path whose local version is newer than the peer's (or the peer lacks it) and whose hash differs from
  the peer's, keep `<outbox>/<path>` with that content; remove every other outbox file. Write outbox files, then the
  note (atomic). Prune tombstones > 30 days and backups > 14 days.
- [ ] **Step 4:** run → pass.
- [ ] **Step 5:** commit "machine_sync: two-way data with newest-change-wins".

### Task 4: Daily tasks, processes and freezes

**Files:**
- Create: `machine_sync/daily.py`, `machine_sync/procs.py`
- Test: `tests/machine_sync/test_daily.py`

**Interfaces:**
- Produces: `processes() -> list[Proc]` (`Proc(pid, exe, cmdline)` via PowerShell `Get-CimInstance
  Win32_Process`, empty list on failure); `load_daily_tasks(cfg) -> list[dict]` (`{id, claim, cwd, cmd}` resolved
  absolute; dumped by the launcher venv `python -c` into `MachineSync/tasks.json`, last good dump on failure);
  `busy_repos(cfg, tasks) -> set[str]`; `running_tasks(tasks, procs) -> set[str]`; `holds_claim_today(cfg, now:
  datetime) -> bool` (from `daily_claim.json`); `code_frozen(cfg, now) -> bool` (holds today's or yesterday's claim
  and `now` is before 09:00 the day after the claim); `venvs_in_use(procs) -> set[Path]`.

- [ ] **Step 1: Tests** `test_busy_repos_from_cwd_and_cmd` (IBKR task with `../Trend/AIJPMT1A_build/live/targets`
  in its command → {"IBKR", "Trend"}); `test_running_matches_command_line`; `test_code_frozen_until_nine_next_day`
  (claim 17 Nov 09:41 → frozen at 17 Nov 23:00 and 18 Nov 08:59, not at 18 Nov 09:00); `test_not_frozen_without_claim`;
  `test_venv_in_use`.
- [ ] **Step 2:** run → fail. **Step 3:** implement. **Step 4:** run → pass.
- [ ] **Step 5:** commit "machine_sync: daily tasks, running processes and freezes".

### Task 5: Daily claim on GitHub and the launcher guard

**Files:**
- Create: `machine_sync/claims.py`
- Modify: `config.py` (`TaskConfig.claim: str | None = None`), `task_runner.py` (`start(task_id, take_over=False)`),
  `app.py` (`start_task(task_id, take_over: bool = False)`, return `claimed_by`), `static/index.html` (take-over
  confirm), `reminder.py` (no banner when another PC holds today's claim), `tasks.yaml` (`claim: daily` on both
  tasks), `README.md` (one paragraph)
- Test: `tests/machine_sync/test_claims.py`, `tests/test_claim_guard.py`

**Interfaces:**
- Produces: `ClaimResult(ok: bool, holder: str | None, at: str | None, error: str | None)`;
  `claim(repo: Path, claim: str, day: str, machine: str, take_over: bool = False) -> ClaimResult`;
  `holder(repo: Path, claim: str, day: str) -> ClaimResult`; ref `refs/daily-claims/<claim>/<day>`; commit message
  `daily claim <claim> <day> by <machine> at <ISO local time>`; `prune(repo, keep_days=30)`.
- Launcher: refusal error text `"<label> for <day> was already started on <holder> at <HH:MM>. Use Take over only if
  that run has ended or that PC is off."`; unreachable: `"<label>: could not check GitHub for today's run (<reason>);
  not started."`; JSON `{"ok": false, "errors": [...], "claimed_by": "<holder>"}`.

- [ ] **Step 1: Tests** (bare local origin): `test_first_claim_wins`; `test_second_claim_refused` (other machine →
  ok False, holder = first); `test_same_machine_reclaims`; `test_take_over_moves_claim`;
  `test_unreachable_refuses` (origin path removed → ok False, error set); `test_prune_old_claims`. Launcher:
  `test_daily_task_refused_when_other_pc_holds` (patched `claims.claim` → runner.start returns the refusal, no
  process started); `test_task_without_claim_starts_without_check`; `test_take_over_passed_through`.
- [ ] **Step 2:** run → fail. **Step 3:** implement. Claim commit: `git commit-tree <empty tree> -m <message>`,
  `git push origin <sha>:refs/daily-claims/<claim>/<day>` (with `--force` for take over); on rejection
  `git fetch origin +<ref>:<ref>` and read the message. The launcher machine name comes from
  `C:\Users\User\MachineSync\machine.txt` (missing → refuse with "install the sync tool first").
- [ ] **Step 4:** run both suites → pass. **Step 5:** commit "launcher: one daily run per day, claimed on GitHub".

### Task 6: Runner, status, self-update, install

**Files:**
- Create: `machine_sync/status.py`, `machine_sync/runner.py`, `machine_sync/__main__.py`, `machine_sync/install.ps1`
- Test: `tests/machine_sync/test_runner.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces: CLI `python -m machine_sync run [--allow-deletes] [--update-frozen] | status | selftest | install
  --machine desktop|laptop`; `run_once(cfg, now, allow_deletes=False, update_frozen=False) -> str` (the status text).

- [ ] **Step 1: Tests** `test_two_pc_round_trip` (end to end with both helpers: laptop pushes a branch and writes a
  data file; one desktop run → desktop on the branch with the file; status mentions both);
  `test_peer_note_newer_format_stops_import`; `test_lock_skips_overlapping_run`; `test_status_lists_unpushed_and_clashes`;
  `test_selftest_passes`.
- [ ] **Step 2:** run → fail. **Step 3:** implement: lock file in `MachineSync`; order per spec "One run"; status
  layout per spec; log only lines that differ from the previous run's warnings; self-update from `git show
  origin/main:machine_sync/<file>` of the launcher repo into a temp folder, `selftest` there, then replace
  `MachineSync\tool`. `install.ps1 -Machine desktop|laptop`: copy the package to `MachineSync\tool`, write
  `machine.txt`, register "Machine sync" from task XML (time trigger every 5 min, logon, session unlock, wake event
  Power-Troubleshooter 1), `MultipleInstancesPolicy IgnoreNew`, battery allowed, no time limit beyond 1 hour;
  unregister the old "TripSync - update desktop" / "TripSync - export data".
- [ ] **Step 4:** run all tool tests and launcher tests → pass. **Step 5:** commit "machine_sync: runner, status,
  install".

### Task 7: Desktop rollout and laptop handover

- [ ] Real-GitHub claim check: claim `refs/daily-claims/test/<today>` as desktop, read it back, delete it.
- [ ] Create Syncthing folder `desktopsync-data` (`C:\Users\User\DesktopSync`, send-only, shared with the laptop)
  through the desktop's API (home `C:\Users\User\TripSync_syncthing`).
- [ ] `install.ps1 -Machine desktop`; one `run` by hand; read `sync_status.txt`; second run shows no repeats.
- [ ] Write `docs\machine-sync-laptop.md`: the steps and a paste-in Claude Code prompt for the laptop.
- [ ] Ask Stephen before pushing the branch and merging to `main`.
