# Two-way sync between the desktop and the laptop, and one daily run per day: design

17 Nov 2026, revised the same evening after an independent builder review and two requests from Stephen ("go and
implement"; "there shouldn't be duplicate daily process runs"). Replaces the one-way trip sync
(`C:\Users\User\ARCHITECTURE.md`, "Trip sync — as built").

## Why

Stephen develops on either PC: the desktop at home, the laptop away. Whichever PC he sits down at should already
have the latest code and data, within minutes of the other PC being online, with no manual pulls, branch switches
or copying. The trip showed the gap: the one-way sync left the desktop on stale branches (Trend 28 commits, IBKR 51
behind) and data flowed only laptop to desktop. With two working PCs, the daily jobs (MTFA Start of Day, IBKR
paper cycle) must also never run twice for the same day.

## Goals

- **G1 Code follows the PC last worked on.** About 10 minutes after a push from one PC, the other PC is on the same
  branch at the same commit in that repo, unless Stephen is working in that repo there.
- **G2 All branches stay current:** every local branch that tracks a GitHub branch is fast-forwarded on both PCs.
- **G3 Data flows both ways:** a Git-ignored data file created, changed or deleted on either PC is the same on the
  other PC about 10 minutes later (both online).
- **G4 Catch-up on coming online:** a run at logon, unlock and wake, then every 5 minutes.
- **G5 Gaps are visible on both PCs in one file** (`sync_status.txt`).
- **G6 One daily run per day:** the daily tasks run on one PC per day, enforced at start.
- **G7 One tool, both PCs**, versioned in the launcher repo, run from an installed copy.

## Non-goals

- Carrying uncommitted edits or unpushed commits (Stephen: "pushed only, flag gaps"). The tool never commits,
  pushes code, merges, rebases or forces a branch.
- Secrets, virtual environments, `node_modules`, caches, logs folders, lock files (excluded as today).
- The VPS (phase 6 must fit later; see "Phase 6 fit").
- Running `npm ci` automatically.
- Guarding daily tasks started outside the launcher (for example `daily_cycle.py` from a shell).

## Anti-goals

- Losing work: a file replaced or deleted by the sync without a backup when it had also changed on that PC; a
  branch moved off commits that exist only on that PC; a switch over uncommitted edits.
- Changing code or data under a running daily task; changing trading code between building and trading a day's
  list on the PC that runs the day.
- Silent clashes or silent permanent differences between the PCs.
- The same daily task run on both PCs for the same day.
- Files bouncing back to the PC they came from.

## Constraints

- Windows 11 on both PCs, same user folder and repo paths, Sydney time, clocks NTP-synced.
- Standalone Python 3.12.10 at `C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe` (present on the
  desktop; the laptop setup installed the same). The tool is standard library only.
- Syncthing 2.1.7 over Tailscale only. Desktop Syncthing home `C:\Users\User\TripSync_syncthing`. Existing folder
  `tripsync-data` (`C:\Users\User\TripSync`): send-only on the laptop, receive-only on the desktop.
- Claude desktop app sandbox: writes under `%LOCALAPPDATA%` and HKCU do not reach real Windows; files under
  `C:\Users\User`, scheduled tasks and firewall rules do.
- GitHub over HTTPS with stored credentials on both PCs; the network can be down just after boot.
- Data: about 5,900 files, 4.65 GB; 200 MB to 1 GB a day of change.
- Daily tasks are started by hand from the launcher (`tasks.yaml`). The IBKR paper cycle has two presses (build the
  list; trade it overnight until about 08:20 Sydney) and reads Trend's `live/targets`.

## Approaches

| Approach | Trade-off | Decision |
|---|---|---|
| **A. One sync tool on both PCs, both ways:** code through GitHub with branch following; data through one Syncthing outbox per PC with full manifests and newest-change-wins | Most code; works offline, survives weeks off, every clash flagged with a backup | **Chosen** |
| B. Syncthing both ways directly on the data folders | Least code; fights Git in mixed folders, copies half-written outputs, scatters `.sync-conflict` files | Rejected |
| C. One PC holds everything, the other works remotely | Nothing to sync; host must be on (the desktop was off 29 Oct to 17 Nov), no offline work | Rejected |
| D. Phase 6 now (VPS is the only data writer) | Cleanest end state; much bigger build | Later; A is built to fit it |
| Data rule "take only if unchanged since last agreement" with per-file "replaces" (first draft) | Loses or silently strands a change when a file reverts to an earlier version (builder review) | Replaced by newest-change-wins with manifests |
| Duplicate-run guard: one named "runner" PC setting | Must be switched by hand when travelling | Rejected for a first-come claim per day |
| Duplicate-run guard through Syncthing files | Minutes of delay: both PCs could start inside the window | Rejected for an atomic claim on GitHub |

## Design

### Pieces

- Source: `Marco\launcher\machine_sync\` (package), tests in `Marco\launcher\tests\machine_sync\` (unittest).
- Installed copy and state: `C:\Users\User\MachineSync\` (outside every repo): `tool\` (the installed package),
  `machine.txt` (`desktop` or `laptop`), `state.json`, `sync_status.txt`, `sync.log`, `backup\<date>\...`,
  `daily_claim.json` (today's claim as last seen).
- Outboxes: laptop `C:\Users\User\TripSync` (existing folder), desktop `C:\Users\User\DesktopSync` (new Syncthing
  folder `desktopsync-data`, send-only on the desktop, receive-only on the laptop). Each holds `_state\<machine>.json`.
- Scheduled task "Machine sync" on each PC: every 5 minutes, at logon, at unlock, on wake; one instance at a time.
  Replaces "TripSync - update desktop" and "TripSync - export data". "TripSync - Syncthing" stays.
- Self-update: after fetching the launcher repo, if `origin/main`'s `machine_sync\` differs from the installed copy,
  the run copies it to a temporary folder, runs its `selftest`, and only then replaces `tool\`. The checked-out
  launcher branch never matters to the tool. Since 18 Nov 2026: the self-test also runs a dry run of the core
  decisions on two made-up PCs in a temporary folder; no update while a daily task runs on the PC or its code is
  frozen for today's run, or while `MachineSync\hold_update.txt` exists; the replaced copy stays in `tool.old`.
- Note format carries a version. A PC that reads a newer format than it knows stops importing and following, and
  says "update the sync tool on this PC".

### One run

1. Read this PC's state and the other PC's note.
2. Code step for each repo.
3. Data: scan this PC, import from the other PC, then refresh this PC's outbox and note.
4. Write `sync_status.txt`; append changes and new warnings (not repeats) to `sync.log`.

### Daily tasks and freezes

- Daily tasks are those in `tasks.yaml` with `claim: daily`. The tool reads `tasks.yaml` through the launcher venv
  (a JSON dump), falling back to the last good dump.
- **Busy repos:** every repo that a daily task's folder or command line points into (Trend and IBKR today).
- **Running:** a process whose command line matches a daily task's command, or runs its script (by file name) or
  module and subcommand (`-m src.operations run`) from any folder, so a run started from a terminal counts; or the
  task's progress file (Trend's `data/logs/sod_progress.json`) says running and names a live process.
- **Code freeze:** on the PC that holds today's daily claim, busy repos do not change code from the claim until 09:00
  Sydney the next day (the overnight cycle trades with the code that built its list). `machine_sync.py run
  --update-frozen` updates them anyway, by hand.
- **Data freeze:** while a daily task runs on this PC, nothing is imported into busy repos. Export continues but
  takes only files unchanged for 60 seconds, checked again after copying.
- A virtual environment whose `python.exe` is in use by a running process is not `uv pip sync`ed; status says to
  close that app.

### Code step (per repo)

1. `git fetch --all --prune` (failed: status "could not reach GitHub", skip the repo).
2. Fast-forward every local branch not checked out that is strictly behind its GitHub branch.
3. **Working here** = uncommitted files (tracked changes or untracked files Git does not ignore), commits on the
   current branch that its GitHub branch lacks, a Git operation in progress (rebase, merge, cherry-pick, bisect),
   or a running daily task in this repo. A branch whose GitHub branch was deleted does not count as unpushed; the
   status says "branch deleted on GitHub".
4. **Leader** = the other PC if its note's last activity in this repo is later than this PC's. Last activity is the
   newest HEAD reflog entry not made by this tool (its Git moves carry `GIT_REFLOG_ACTION=machine-sync`), or the
   newest uncommitted file's modified time if later.
5. Act:
   - **Frozen** (code freeze above): no moves; status line.
   - **Working here:** never switch branch; `git merge --ff-only` the current branch if strictly behind GitHub (Git
     refuses to touch an edited file; flagged). Both PCs working: status "work in progress on both PCs".
   - **Not working here, other PC leads, its branch is on GitHub:** move to its branch at its HEAD if GitHub has
     that commit, else at its last pushed commit (status "laptop has N unpushed commits"). Reuse the local branch of
     that name if moving it loses nothing, else stop and flag; create it tracking `origin/<branch>` if missing.
     `--no-overwrite-ignore` so ignored data files are never replaced by a checkout.
   - **Otherwise** (this PC leads, no note, or the leader's branch is not on GitHub): fast-forward the current branch
     if strictly behind. If its GitHub branch was deleted and the PC is idle: move to the repo's default branch
     (local branch kept). Split branch: flag "merge by hand".
6. If HEAD moved: changed `requirements.lock.txt` → `uv pip sync` into that app's `.venv` (unless in use);
   changed `package-lock.json` → status "run npm ci in <folder>"; a running dashboard from that repo → status
   "restart <app> to use the new code".

### Data step

**What is data:** Git-ignored, non-secret files under the 8 repos plus `FXMGT` outside `JPMQFX01_build` (as
today), minus: PostgreSQL data folders (a `PG_VERSION` file), SQLite `-wal`/`-shm`/`-journal` files, `*.lock`,
`*.sync-conflict-*`, Syncthing's own files. A file is imported only if this PC's Git also ignores it.

**SQLite databases** (header `SQLite format 3`) move as a whole and only when no `-wal` or `-journal` file sits next
to them on the sending PC (export) and on the receiving PC (import), so neither app has it open.

**Versions.** Each PC records per path: content hash, change stamp (UTC time plus machine name), the stamp it
replaced, and whether it is deleted (a tombstone). The stamp of a change is when this PC first saw it; a path seen
for the first time with no history takes the file's modified time (so the first run on both PCs keeps the newer
copy, not whichever PC ran first). A path that reappears after a tombstone is a new change.
Which version is newer (18 Nov 2026 review): each version carries a version vector (per PC, the stamp of that
PC's latest change it includes, from that PC's own clock, never going backwards). A version that includes every
change of the other wins; only versions changed on both PCs independently fall back to the later stamp. So a PC
whose clock is ahead cannot undo a later change made from its own version. The status warns when the other PC's
note, heartbeat or newest change is stamped more than 30 s in this PC's future.

**Note:** each PC's note lists every data path with its version (tombstones kept 30 days and until the other
PC's note shows the same deletion, at most 90 days, so a PC that was off for weeks does not bring files back).

**Outbox:** holds exactly the files whose version on this PC is newer than the other PC's version (per its note)
and whose content the other PC lacks. Files are written before the note that names them. When the other PC's note
shows the same content, the outbox copy is removed. Nothing bounces back.

**Import** for each path in the other PC's note:

| Situation | Action |
|---|---|
| Same content (or both deleted) | in sync; both keep the later stamp |
| This PC's version is newer | nothing (this PC's outbox carries it) |
| The other PC's version is newer, content in its outbox with the right hash | replace (or delete for a tombstone) |
| The other PC's version is newer, content not arrived yet | wait for the next run |
| Replacing or deleting a file this PC had changed since the other PC last saw it (a clash) | back up this PC's copy to `MachineSync\backup\<date>\...`, then replace; list it in the status on both PCs |
| Busy repo with a daily task running, file changing right now, or tracked by this PC's Git | skip this run (the last stays flagged) |

Every deletion is backed up. **Deletion brake:** more than max(50, 2% of files) deletions in one run, or more than
max(150, 5% of files) in one day (runs added up, `deleted_today` in `state.json`), are held and flagged; `machine_sync.py run --allow-deletes` lets them through. Backups older than 60 days are pruned (14 until 18 Nov 2026).

Both PCs apply the same rule to the same two versions, so they converge; restoring a backup is a new change and
wins.

### One daily run per day

- `tasks.yaml`: `claim: daily` on MTFA Start of Day and IBKR paper cycle. Tasks sharing a claim name share one claim
  per day (date in the task's timezone).
- Before starting such a task, the launcher pushes a claim to the launcher's GitHub repo:
  `refs/daily-claims/<claim>/<YYYY-MM-DD>` → a commit with no parent whose message names the PC and time. GitHub
  accepts only the first (a second, unrelated commit is not a fast-forward), so two PCs cannot both claim.
- Before claiming (18 Nov 2026 review): every repo the task uses, and the launcher, must be on its default branch with
  no Git operation in progress, no unpushed commits and nothing split from GitHub (`machine_sync/startcheck.py`, local
  checks only), and every newer version the other PC's note lists in the daily tasks' repos has been taken (the
  import's own rules: `pending_from_peer`), and no app folder of the task's repos waits in `pending_uv.json` (every
  failed `uv pip sync` waits there and is retried each run); else refuse and offer **Start anyway**
  (`allow_unsynced`). Edited or staged tracked files are only a warning (shown with the run, recorded in the claim as
  `+edits: Trend 2 files`): Start of Day rewrites some of Trend's itself. The claim's commit message lists each repo's
  HEAD below its first line. The code step follows the other PC in these repos only on their default branch.
- Claim already held by this PC: start (re-runs and the cycle's second press work). Held by the other PC: refuse
  with "already started on laptop at 10:02". Not reachable: refuse ("could not check GitHub").
- **Take over** (button after the refusal, with a warning to use it only if the other PC's run ended or it is off):
  force-pushes this PC's claim and starts. Fencing (18 Nov 2026): refused while the other PC's note or heartbeat
  is under 15 minutes old or its note lists a daily task running (`running_tasks`, new note field; an older
  note's `repos.*.running`); `force_take_over` (a second confirmation on the page) overrides.
- The sync tool records today's claim (`daily_claim.json`); the launcher's Start of Day reminder is not shown on the
  PC that does not hold it.
- Claims older than 30 days are deleted after a claimed task has started, in the background (never holding the
  start or run.lock).

### What Stephen sees (`C:\Users\User\MachineSync\sync_status.txt`)

```
Sync status on desktop, 17 Nov 21:40 (laptop's note from 21:37)
Today's daily run: claimed by laptop at 09:41
Code
  Trend      main @ ae6cc16      same as laptop
  IBKR       master @ 3b17c2e    laptop has 2 unpushed commits (since 20:10): push them to share
  FOMC       master @ 088ec65    edits on this PC (3 files): stayed here, not switched
Data
  in sync (5,862 files)
  2 files changed on both PCs today: laptop's kept, desktop's copies in MachineSync\backup\2026-11-17
```

### Phase 6 fit

When the VPS becomes the market-data writer, its folder is a third outbox read with the same rules, and the
market-data folders stop being exported by the PCs (a list in the tool's settings). The code step and the daily
claim do not change.

### Rollout

1. Build on a launcher branch with tests that simulate both PCs (bare "GitHub" repo, two working copies, two
   outboxes, Syncthing simulated by copying). Check the claim against the real GitHub with a test ref, then delete it.
2. Desktop: install the tool, create the `desktopsync-data` folder, register "Machine sync", remove "TripSync -
   update desktop", run once by hand.
3. Merge and push with Stephen's OK. Laptop (Stephen, or Claude Code there with a written prompt): pull the
   launcher, install, accept `desktopsync-data` as receive-only, register, remove "TripSync - export data", run once.
4. Watch runs on both PCs; update `ARCHITECTURE.md` and the runbook.

## Left to the builder

File formats inside `_state` and `state.json`, hash length, the hash cache, log wording, test layout, how the
launcher shows the take-over prompt, Syncthing folder label.
