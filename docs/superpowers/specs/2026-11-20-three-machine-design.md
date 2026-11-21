# The VPS as the third machine, and the main one

**Design.** VPS Claude, Fri 20 Nov 2026, about 21:00 Sydney. No secrets in this document.
**Status: approved by Stephen on Fri 20 Nov 2026, in chat on the VPS: "Approve as recommended".** So section 9 is
decided as recommended:

- full parity;
- automatic start on the VPS;
- 16 GB of memory;
- a hosted outside dead-man;
- `C:\IBKR` moved, with a junction, on a weekend.

Items 7 (Norgate) and 8 (the Node download) are steps for later.

## 0. Changes while building phase 1 (branch three-machines, 21 Nov 2026)

These take precedence over the sections below.

- **Outbox relay (5.2).** An outbox sends its own PC's changes, as designed. It also sends a version another PC
  made once that PC's sync has been quiet for `RELAY_AFTER_H` (6 h).
  - Why: otherwise a PC that lacks a file (one joining, one that lost the file) would wait for the PC that made it
    to come back on.
  - Normal days send nothing twice. Syncthing's relay through the VPS's copy of an outbox (tested, simulated) covers
    the hours before that.
- **Logs never travel by Machine sync (5.3, 5.6).** `data_files.SKIP_DIRS` holds `logs`; the one exception is
  Trend's `data/logs/sod_<t>.json`. So:
  - IBKR's `logs\heartbeat.json` reaches the VPS only through the two heartbeat Syncthing folders set up on 21 Nov,
    `ibkr-heartbeat-desktop` and `ibkr-heartbeat-laptop`, received at `C:\IBC\heartbeat\<pc>`. These shares are
    permanent: they are not removed in phase 3.
  - On a day the VPS runs the cycle, its heartbeat is local, and the cycle watch (work item D) reads it there.
  - The Operations page reads the cycle from the database, not from log files.
- **Automatic start (5.4).** It is configured per task in tasks.yaml:
  - `auto: {pc: vps, at: "09:30"}` for Start of Day;
  - `auto: {pc: vps, at: "15:00"}` for the cycle's first press.
  - The key is `pc`, not `on`, because YAML reads a bare `on` as true.
  - It acts only on that PC, and only while `MachineSync\auto_start.on` exists there. That file is made by hand at
    phase 7.
  - It starts when the task's reminder rules say it is due, and never makes the second press.
  - A day another PC holds is left to it. Every other refusal is retried 5 minutes later and never overridden.
  - With `LAUNCHER_NOTIFY` (a PowerShell script taking `-Message`; on the VPS, `C:\IBC\send-alert.ps1`), each
    automatic start, each day left to another PC, and the first failure of a day are sent on Telegram.
- **"Run today here" and "Reserve a day…" (5.4)** are links under "Today's run" on the launcher page
  (`POST /api/day/reserve[?day=YYYY-MM-DD]`).
  - They claim the `daily` claim for that day without starting anything.
  - The claim's message says "reserved by hand on <pc>: nothing started".
  - For a later day, the code freeze is recorded from the start of that day.
- **Note format 2.** An older (two-PC) tool stops following a three-machine note until it has updated itself, as
  designed.
- Tests: `tests/msync/test_three_machines.py` (11) and `tests/test_auto_start.py` (16).

---

## 1. Summary

The VPS becomes a full third machine, the same as the desktop and the laptop:

- The same eight repos, at the same paths relative to the user folder.
- The same tools: Python 3.12.10 venvs, Node, the launcher.
- The same Machine sync. Code comes through GitHub. Data comes through a third Syncthing outbox, `VpsSync`.

Any of the three can run a day. **By default the VPS runs every day** (D65, Stephen: "we will assume vps will be
the main unless i manually run it on desktop or laptop"). On a run day, the VPS does this by itself:

1. It starts Start of Day at 09:30.
2. It makes the cycle's first press when Start of Day ends.
3. It makes the second press within a few minutes of Stephen's approval. Stephen can approve on any of the three
   machines' Operations page.

To run a day on the desktop or the laptop instead, Stephen presses **"Run today here"** on that machine before
09:30. The VPS sees the claim and stands down.

Each part is reused or built as follows:

| Part | Status |
|---|---|
| Daily claim, run lock, freezes, resume task, "run ended" heartbeat | Already exist or are in tonight's merge. Reused unchanged. |
| Machine sync | Generalised from two machines to three (section 5.2). |
| VPS outage alert | New: a dead-man outside the VPS (section 5.6). |
| Laptop watch | Becomes a cycle watch that also covers a day on the VPS (section 5.6). |

## 2. Decisions this builds on

- **D56** (review, 20 Nov): move the overnight cycle to the VPS, with an outside dead-man. It counts as done after
  5 paper nights watched from outside.
- **D65** (merging tonight, IBKR 6a50269): the VPS is the main machine for the whole day, Start of Day and both
  presses.
  - Laptop-class speed is accepted.
  - So is the late-data risk: a 14:30 cut-off can miss the 15:15 envelope deadline and end HOLD.
  - D65's readiness list (memory, Norgate, Trend on the VPS, one timed trial) is the exit test of phase 5 below.
- **Launcher BACKLOG 1.10** (rewritten): "The VPS runs the daily run: Start of Day and the night, with an outside
  dead-man".
- **Launcher BACKLOG 2.4**: the VPS watch knows when a run has ended.
- **Two-way machine sync design** (17 Nov): its "Phase 6 fit" foresaw the VPS as a third outbox read with the same
  rules.

## 3. Goals, non-goals, constraints

**Goals**

- G1. Any of the three machines can run a day. The VPS runs it unless Stephen starts it elsewhere.
- G2. Code and data reach every machine the same way they do between the desktop and the laptop today:
  - every 5 minutes;
  - newest change wins;
  - clashes are backed up;
  - the deletion brake applies.
- G3. One day, one machine.
  - The daily claim on GitHub is the first fence.
  - The database run lock is the second (`pg_try_advisory_lock`, from tonight's merge).
- G4. A stopped or dead VPS raises an alert from outside the VPS within 15 minutes, on run nights.
- G5. When Stephen is away, a laptop that is off for weeks still catches up. The desktop and the laptop no longer
  need to be on at the same time, because the always-on VPS relays between them.

**Non-goals**

- Making the database or the paper Gateway highly available. Both stay on the VPS.
  - A VPS outage stops the cycle wherever it was started.
  - Only Start of Day can still run elsewhere (section 5.5).
- Anything on the live account or the live Gateway (port 4001).
- Moving the launcher or the dashboards off localhost, or opening any port.

**Constraints**

- These are Stephen's standing rules and they hold throughout:
  - No port opened to the internet.
  - Claude never types, stores or prints a password or token.
  - No IBKR account settings change.
  - Gateway or IBC config changes are shown to Stephen first.
- Steps that need administrator rights run as a script that Stephen approves with one UAC click.
- The VPS's user folder is `C:\Users\Administrator`, not `C:\Users\User`. Machine sync is already relative to the
  user folder (`USERPROFILE`), and the repos use relative paths, such as tasks.yaml's
  `../Trend/AIJPMT1A_build/live/targets`. So the account stays as it is.

## 4. The three machines today

| | Desktop | Laptop | VPS |
|---|---|---|---|
| User folder | `C:\Users\User` | `C:\Users\User` | `C:\Users\Administrator` |
| Repos | all 8 | all 8 | IBKR only, at `C:\IBKR` |
| Machine sync | yes (outbox `DesktopSync`) | yes (outbox `TripSync`) | no |
| Python | standalone 3.12.10 | standalone 3.12.10 | uv 3.12.10 |
| Node | yes | yes | **no** |
| Paper Gateway, PostgreSQL | no (uses the VPS's) | no (uses the VPS's) | yes |
| Norgate | yes | yes | **no** |
| CPU / RAM | fast / ample | laptop | 4 vCPU EPYC (about 3.6x slower per thread than the desktop) / **8 GB, 2.3 GB free now** |
| Disk free | | | 61 GB of 100 GB |
| Always on | no | no (trips) | yes: autologon; Windows Update never restarts it |

The VPS's Syncthing (v2.1.7) listens on its Tailscale address only, and it already knows the desktop and the
laptop, through the `ibkr-settlements` folder.

## 5. Design

### 5.1 Layout on the VPS

```
C:\Users\Administrator\
  Marco\Australia-Rates  Marco\CB Pricer  Marco\Curve  Marco\FOMC  Marco\launcher
  IBKR\            <- the current C:\IBKR, moved here (same disk: a rename, nothing is copied)
  Trend\           <- new clone (AIJPMT1A_build inside)
  FXMGT\JPMQFX01_build\
  MachineSync\     <- tool\, state, machine.txt = "vps", backup\<date>\
  VpsSync\         <- this machine's outbox (send-only)
  DesktopSync\  TripSync\   <- the other two outboxes (receive-only)
C:\IBKR  ->  junction to C:\Users\Administrator\IBKR
```

**Why move IBKR and leave a junction.** Every machine then has the same layout under its user folder, which is what
Machine sync and the relative paths expect. Everything that names `C:\IBKR` keeps working unchanged through the
junction:

- IBC scripts;
- the scheduled tasks (settlements pull, database backup, health check);
- `IBKR_SETTLEMENTS_DIR`;
- the existing `.venv`, whose launchers hold `C:\IBKR\...` paths.

Syncthing's `ibkr-settlements` folder is re-pointed to the real path, so Syncthing never works through a junction.
The move happens on a weekend:

- with no cycle and no settlements pull running;
- with the Gateway untouched;
- after Syncthing has been paused.

**Tools**

- **Python:** the uv-managed CPython 3.12.10 that already runs IBKR's venv.
  - Machine sync's scheduled task uses its `pythonw.exe`. The install takes it from `sys.executable`, so no code
    changes.
  - Venvs: launcher, IBKR (existing), Trend. Each is built with `uv venv --python 3.12.10` and
    `uv pip sync requirements.lock.txt`.
  - The four Marco repos and FXMGT get code and data but no venv. Stephen does not run them on the VPS.
- **Node:** the same LTS major version as the desktop, then `npm ci` in `Trend/AIJPMT1A_build/dashboard` and
  `IBKR/dashboard`. Downloading it from nodejs.org is asked first, with the file and its size.
- **Git:** the existing portable MinGit.
  - The VPS's GitHub credential must read all 8 repos and write to the launcher, for the claim refs.
  - Machine sync never pushes code. Anything Stephen commits on the VPS he pushes himself.
- **Launcher:** started at logon in the autologon session, like the Gateway, so it is always there for the day's
  automatic steps. Stephen reaches it, and the dashboards, by RDP. They stay localhost-only.

**Rule for the VPS session:** disconnect RDP, never sign out. Signing out ends the Gateway, the launcher and a
running cycle.

### 5.2 Machine sync with three machines (launcher `machine_sync`)

The two-machine rules stay. "The peer" becomes "every other machine". These are the changes:

| Area | Two machines today | Three machines |
|---|---|---|
| `settings.py` | `MACHINES = (desktop, laptop)`; `peer`; two outboxes | adds `vps` with outbox `VpsSync`; `peers` (the other two); `outboxes()`; the note format number goes up by one |
| Code: who leads | the peer, if its last activity is newer | the machine with the newest activity among the three. The claim holder's busy repos stay frozen until 09:00 the next day (unchanged) |
| Data: import | from the peer's note and outbox | from every peer's note. Per path, the version that includes the others' changes wins (version vectors, unchanged). Only truly concurrent changes fall back to the later stamp. The content is taken from any outbox that holds that hash |
| Data: outbox | files newer than the peer's version that the peer lacks | **only this machine's own changes** that at least one peer lacks. A copy is removed when **every** peer's note shows that content or a later version. Imported files are never staged again |
| Tombstones | kept until the peer's note shows the deletion (30-90 days) | kept until every peer's note shows it (30-90 days) |
| Peer not yet joined | n/a | nothing is staged for a machine that has never written a note, so a new machine does not cause a 4.65 GB copy into every outbox |
| Take-over fence | the peer's note or heartbeat is under 15 min old | the same check, applied to **the machine that holds the claim** |
| Status | one peer | one line per machine: last seen, data still to arrive, clock skew |
| Syncthing folders it must not write | everything except the two outboxes | everything except the three outboxes |

**Relay.** Each outbox folder is shared with all three machines. Syncthing hands a folder's files on through any
device that holds them. So when the desktop is off, the laptop still gets the desktop's latest changes from the VPS's
copy of `DesktopSync`, and the other way round. That is why an outbox holds only its own machine's changes: there
are no duplicates and no bounce. **Phase 3 checks this in a test.**

**Upgrade order.** The note format number goes up by one. A machine running the older tool already refuses to
follow a newer note and says so. So:

1. The change is merged to the launcher's main branch.
2. The desktop and the laptop update themselves (self-update with selftest, within 5 minutes when on).
3. Only then is the VPS installed.

The two PCs ignore the VPS until its first note appears.

**Tests.** The existing simulation (a bare "GitHub", working copies, outboxes, Syncthing simulated by copying) is
extended to three machines. Cases:

- the laptop off for 3 weeks while the desktop and the VPS both change things;
- the desktop off while the laptop picks up the desktop's changes via the VPS;
- the same file changed on two machines;
- a deletion while one machine is off;
- a three-way race for the claim;
- a take-over when the holder is alive, and when it is dead;
- the upgrade order, with an old-format peer;
- a joining machine with seeded data.

### 5.3 Data: joining the VPS, and what is shared

**Seed, then join.** The VPS joins with a copy of the desktop's data already in place, so its first run finds
matching content and nothing has to travel through the outboxes:

1. Desktop Claude lists the data files with Machine sync's own rules and packs them with `tar`, which keeps
   modified times. That is about 4.65 GB in all, of which Trend's data folder is about 2.4 GB.
2. The pack goes over a temporary Syncthing folder on Tailscale. It can resume if interrupted.
3. It is unpacked on the VPS before the VPS's first sync run.

A file seen for the first time takes its modified time as its stamp (as designed on 17 Nov). The seeded copies
match the desktop's by hash, so nothing moves. Anything changed since the seed comes in the normal way.

**What the VPS contributes.** Its data inside the repos is small today:

- `IBKR\backups\vps\*.dump`, 30 kept, about 150 KB each. Sharing them also gives off-site copies of the database
  backup on the desktop and the laptop.
- `IBKR\logs\settlements.log`, written only by the VPS, so there is no clash.

`IBKR\data\settlements` is a Syncthing folder that the VPS writes itself (send-only). Machine sync leaves it alone on
all three machines, as it does today. `.env` files are never synced; they are excluded as secrets, as today.

**When the VPS runs the day,** Trend's export and envelope folders and IBKR's logs reach the desktop and the laptop
within about 5-10 minutes:

- a file must be unchanged for 60 s before it is exported;
- then there is one sync run on each side.

So the Trend and Operations dashboards on the desktop show the VPS's day. The Operations page reads the database
live; only its file-based parts lag by those minutes.

### 5.4 The day: who runs it, and how

**The claim with three machines.** The claim is unchanged: one first-come GitHub ref per day,
`refs/daily-claims/daily/<date>`, mirrored in `MachineSync\daily_claim.json`. What is new is a **default holder**
setting, `vps`, in the launcher's settings, which every machine reads:

- **On the VPS,** at 09:30 on a trade day, the launcher tries to claim the day.
  - If no other machine holds the claim, the VPS takes it and starts "MTFA Start of Day", exactly as a press would.
  - If the desktop or the laptop already holds the day, the VPS stands down. It sends Telegram: "today is the
    laptop's".
- **On the desktop or the laptop,** a new launcher button, **"Run today here"**, claims the day without starting
  anything.
  - Stephen presses it before 09:30.
  - It can also reserve a future date (for example "Monday on the laptop"); the claim ref is simply written for that
    date.
  - Starting Start of Day by hand on a PC still claims the day, as today.
- **The launcher's reminders** show only on the machine that holds the day.
  - On the VPS, the "press" is automatic.
  - Stephen gets a Telegram at each step: started, GO or HOLD, waiting for approval, second press started, night
    ended.

**One trade day on the VPS**

| Sydney time | What happens | Started by |
|---|---|---|
| 09:00 | Gateway restart (IBC). The code freeze from yesterday's day ends; the VPS pulls code merged since. Code merged to `main` on day N runs from day N+1 | IBC, Machine sync |
| 09:30 | Claim, then Start of Day (waits for closes until 14:30). The settlements pull also starts at 09:30 | VPS launcher (automatic) |
| about 15:00 | Start of Day ends: GO or HOLD; the envelopes are in `live/targets` | |
| when Start of Day ends (not before 15:00) | First press: `run --mode paper`. It stops at "waiting for approval" and Telegram says so | VPS launcher (automatic) |
| by about 16:10 | **Stephen approves** on any Operations page (section below) | Stephen |
| within 2 minutes of approval | Second press: `run` resumes the approved cycle | resume task on the VPS |
| 16:25 to about 08:20 | Windows (ASX, London, CME), reconcile, Telegram summary. The heartbeat ends with `"run": "ended"` | the cycle |
| every 10 minutes, 16:00-08:30 | If the approved cycle is not running and not done, start it again (D56, `scripts/resume_if_needed.py`). The database run lock makes a second copy impossible | resume task (**Stephen registers it**) |

**How the approval reaches the VPS.** `approve` only stamps the database. The Operations page runs
`python -m src.operations approve CYCLE --by NAME --expect HASH --mode paper` on its own computer, and all three
computers use the one database on the VPS. So Stephen can approve in any of three places:

- on the desktop's or the laptop's Operations page, as today;
- on the VPS's page, over RDP;
- from the command line on any of them.

The VPS's resume task sees the approved cycle and makes the second press. That task runs every 10 minutes from
16:00. **This design asks for every 2 minutes from 15:00 to 16:30**, so an approval at 16:15 still makes the ASX
window at 16:25. Desktop Claude is asked to confirm that nothing in `approve` requires the approving PC to hold the
day.

**Automatic start (needs Stephen's OK).** Start of Day has been started by hand on purpose. On the VPS this design
starts it automatically, because Stephen will not be RDP'd in every morning. The human gate stays where it matters:
nothing trades until Stephen approves the list.

### 5.5 Running a day elsewhere, and when the VPS is down

| Situation | What to do |
|---|---|
| Stephen wants the desktop or the laptop for a day | Press "Run today here" before 09:30 (or the day before). The PC connects to the VPS's Gateway and database, as today: `IBKR_TARGET=vps`, client ids 10-19 or 20-29 |
| The VPS's Start of Day has started but Stephen wants to switch | Stop it on the VPS's launcher, then take over on the PC. The fence refuses while the VPS's heartbeat is under 15 minutes old; "force take-over" is for a VPS that is up but stuck |
| The VPS is down in the morning | Start Start of Day by hand on the desktop or the laptop: the claim is taken over once the VPS has been silent for 15 minutes. The envelopes are made. **The cycle cannot run until the VPS is back, because the database and the Gateway live there.** If it is back before 16:10, the PC that holds the day makes the presses against it |
| The VPS dies overnight | The outside dead-man alerts. When the VPS is back (autologon, then the Gateway logon task), the resume task restarts `run`, which resumes the cycle. Missed windows are not traded, and the reconcile reports them |
| The VPS is lost (rebuild) | Contabo snapshot, or a new VPS from the runbook. The database comes from the latest `trading_vps_*.dump`, which every machine now holds through the data sync |

### 5.6 Watching

**Inside the VPS: the cycle watch** (replaces `laptop-watch.ps1`; this is BACKLOG 2.4):

- It reads today's holder from the claim ref.
  - If the holder is the desktop or the laptop: it watches that machine's connection to the Gateway, as today.
  - If the holder is the VPS: it watches the local cycle, through the heartbeat file's age and a loopback API
    connection with a client id in 1-9.
- The window runs **until the heartbeat says `"run": "ended"`**, and no longer stops at 08:15.
  - If "ended" has not arrived by 08:45, it alerts. The Gateway restarts at 09:00.
  - This removes the false alarm when a night ends early or late.
- Alerts go to Telegram, as today.

**Outside the VPS: the dead-man** (D56). Nothing on the VPS can report the VPS's own death, so:

1. **A hosted heartbeat check** (for example healthchecks.io, free tier). This is the primary watch.
   - The cycle on the VPS pings `IBKR_HEARTBEAT_URL`: at start, every 5 minutes while running, and at "ended".
   - The check expects a start by 16:30 on trade days, and a ping at least every 15 minutes until "ended".
   - It alerts Stephen by email or Telegram from outside.
   - Stephen creates the account and puts the URL in the VPS's `.env`. Nothing inbound is opened.
2. **The desktop and the laptop, when they are on,** run the same check over Tailscale, every 10 minutes from 16:00 to
   08:30 when the VPS holds the day. The check is read-only: the cycle's last database activity, and a Tailscale
   ping.

**D56 exit:** 5 paper nights run on the VPS and watched from outside, including one deliberate stop that the outside
watch reports within 15 minutes.

### 5.7 Configuration per machine

Each checkout keeps its own `.env`, which is never synced. These keys differ by machine. Values are shown only where
they are not secret.

| Key | Desktop | Laptop | VPS |
|---|---|---|---|
| `IBKR_TARGET` / `IBKR_LOCAL_APP` | `vps` | `vps` | `local` / `gateway` |
| `IBKR_VPS_HOST` | VPS Tailscale address | VPS Tailscale address | not used |
| `IBKR_CLIENT_ID` | 10 | 20 | **1** (set explicitly; never changed between a run and its resume) |
| `DB_HOST` | VPS Tailscale address | VPS Tailscale address | `127.0.0.1` |
| `DB_PASSWORD`, `IBKR_FLEX_TOKEN_*`, `TELEGRAM_BOT_TOKEN` | Stephen | Stephen | **Stephen types or copies them himself** |
| `IBKR_HEARTBEAT_URL` | optional | optional | **the outside dead-man's URL** |
| `IBKR_SETTLEMENTS_DIR` | receives | receives | writes |
| Trend `.env` (FRED, BoK keys), `config/local.yaml` | yes | yes | Stephen copies; any absolute path in it is replaced by the VPS's own (for example the ingest-marker folder) |

**The Flex token can be locked to one IP address.** If it is, the VPS's public address must be added. That is an
IBKR account setting, so it is Stephen's step.

**Preflight** (review, trade operations #8): before a day starts, the holder checks these switches against this
table and refuses a mismatch, such as client id 10 on the VPS. Desktop Claude's backlog has this. This design adds
the VPS column.

### 5.8 Capacity, and the numbers the trial must meet

**Memory.** 8 GB, with 2.3 GB free at present. The Claude app, WorkBuddyAI and Chrome hold about 3.5 GB of it. A run
day adds:

- the Gateway (mostly paged out today);
- PostgreSQL;
- the launcher;
- Start of Day's peak (desktop Claude sends Monday's figure);
- the dashboards, when Stephen opens them over RDP.

**Recommended: 16 GB** (a Contabo upgrade, Stephen's purchase). The VPS is also where Claude maintains it, so
closing the Claude app on every run day is fragile. Pass mark: peak memory in use under 85% during the trial.

**CPU.** Start of Day is estimated at 60-80 minutes of compute on the VPS. Stephen accepted this. Pass mark: on a
normal-data day, the envelopes are ready by 15:00.

**Disk.** About 5 GB of data, about 3 GB of venvs and Node, and up to about 10 GB of outbox copies while the laptop
is off for two weeks. 61 GB is free. The health check warns below 15 GB free.

**Network.** Syncthing over Tailscale, about 0.2-1 GB a day.

### 5.9 Security

- No new listening ports.
  - Syncthing keeps its Tailscale-only address.
  - The launcher and the dashboards stay localhost-only.
  - PostgreSQL, the Gateway and WinRM stay limited to Tailscale.
- The VPS will hold all 8 repos and their data. It is internet-facing through RDP, kept open while Stephen is in
  China. It already holds the database, the paper Gateway session and the Telegram token, so the extra exposure is
  modest. **Recommended for Stephen** (system security settings, so his to change):
  - an account lockout policy for RDP;
  - the Contabo panel firewall (an open item already).
- GitHub credential: read on all 8 repos, write on the launcher only.
- Secrets live only in `.env` files, which are excluded from the sync and from git. They move by Taildrop, as today.

## 6. Who does what

| Work | Repo / place | Who |
|---|---|---|
| A. Machine sync for three machines (5.2), with tests | launcher, branch `three-machines` from `main` after tonight's merge | VPS Claude builds; desktop Claude reviews; Stephen OKs the merge |
| B. Default holder, VPS automatic start, "Run today here" and reserve a date, reminders only on the holder, `vps` in the launcher's machine fence | launcher | desktop Claude (owns the claim and launcher UI), or VPS Claude if desktop prefers |
| C. Resume task every 2 minutes from 15:00 to 16:30; heartbeat pings at start and end; confirm approval works from another PC | IBKR | desktop Claude |
| D. Cycle watch (5.6) replacing laptop-watch; desktop and laptop outside check | IBKR `scripts/vps/` | VPS Claude; desktop Claude reviews |
| E. VPS layout, clones, venvs, Node, launcher at logon, Syncthing, Machine sync install | VPS | VPS Claude (UAC clicks by Stephen) |
| F. Share `DesktopSync` and `TripSync` with the VPS; accept `VpsSync` as receive-only; the data seed | desktop, laptop | desktop and laptop Claude |
| G. Approvals; Norgate (licence, install, sign-in, first download); 16 GB; secrets in `.env`; GitHub credential; hosted dead-man account; register the resume task; Flex token IP | | Stephen |

## 7. Rollout

Each phase has an exit test. Nothing in phases 1-6 touches tonight's or any paper run, which stays on the desktop
or the laptop, run by hand, until phase 7.

| Phase | What | Exit test | Back out |
|---|---|---|---|
| 0 | Stephen approves this design and the decisions in section 9 | | |
| 1 | Build A (and B, C in parallel by desktop Claude) after the Sat 21 Nov merge | All tests pass, including the three-machine simulations; desktop Claude's review | Branch not merged |
| 2 | VPS layout (weekend): move IBKR and add the junction, clone 7 repos, venvs, Node, launcher at logon | All 8 repos clean; the next weekday's 09:30 settlements pull, 09:20 backup and health check all OK | Remove the junction, move the folder back |
| 3 | Syncthing shares (F) and the seed. Merge A, so the PCs self-update. Install Machine sync on the VPS | All three see each other within 15 minutes; 24 h without a clash; test edits go round all three; the laptop gets a desktop change via the VPS with the desktop off | Unregister the VPS task; the PCs carry on as a pair |
| 4 | Trend on the VPS: Norgate first download, Trend `.env` and config | Start of Day's data checks pass by hand | |
| 5 | **Timed trial Start of Day** on a weekend or non-run afternoon (D65 #4) | Envelopes by 15:00 equivalent; peak memory under 85%; output identical to the desktop's for the same inputs | Days stay on the PCs |
| 6 | Cycle watch and outside dead-man (D) | A deliberate stop is reported from outside within 15 minutes; a night ending early raises no false alarm | Keep laptop-watch |
| 7 | VPS becomes the default holder. The first 5 paper nights are watched from outside (D56) | 5 clean nights, then D56 and D65 are done | Set the default holder to none: days run by hand on the PCs |

## 8. Risks

| Risk | Mitigation |
|---|---|
| The VPS is a single point for the database, the Gateway and now the day | Already true for the database and the Gateway. Mitigations: the outside dead-man; the resume task; the database dumps on all three machines; the Contabo snapshot; Start of Day can run on a PC |
| Memory pressure slows Start of Day or pages the Gateway out | 16 GB; trial pass mark; close the apps on run days until upgraded |
| Late data plus a slower CPU means HOLD | Accepted in D65; the trial measures it; a PC can take a day by hand |
| Norgate does not allow a third machine, or does not run on Windows Server | Stephen checks first. If not, the VPS still runs the night: Start of Day stays on a PC with a separate day claim, which is a later design |
| Syncthing relay does not behave as expected | Phase 3 test. Fallback: an outbox also stages imported files for a peer that has been silent for over 24 h |
| Two machines both start a day | GitHub claim, then the database run lock; the take-over fence checks the claim holder |
| Clock skew between machines | Version vectors; Machine sync warns at 30 s; all three sync to time servers (the VPS uses time.windows.com) |
| A path written only for the desktop (`C:\Users\User\...`) in Trend's config | Phase 4 check; preflight; Machine sync and the repos already use relative paths |

## 9. Decisions for Stephen

1. **Approve this design.**
2. **Full parity:** all 8 repos and their data on the VPS, as you asked (recommended). The alternative is only
   launcher, IBKR and Trend.
3. **Automatic start on the VPS** at 09:30 (recommended), with your approval still required before anything trades.
   The alternative is starting by hand over RDP each day.
4. **Memory:** upgrade the VPS to 16 GB (recommended), or close the Claude app, WorkBuddyAI and Chrome on every run
   day.
5. **Outside dead-man:** a hosted heartbeat check, for example healthchecks.io, plus the PCs' check when they are on
   (recommended). You create the account and paste the URL into the VPS's `.env`.
6. **Move `C:\IBKR`** to `C:\Users\Administrator\IBKR` with a `C:\IBKR` junction, on a weekend, with one UAC click
   (recommended).
7. **Norgate:** confirm that the licence covers a third computer and that it runs on Windows Server 2022. If so, you
   sign in on the VPS and start the first full download.
8. **Node.js LTS download** from nodejs.org on the VPS: I will ask with the file name and size at the time.

## 10. Questions for desktop Claude

1. The GitHub remote of each of the 8 repos (the VPS cannot find Trend's).
2. The Node major version on the desktop.
3. Does `approve` from the desktop's page work for a cycle whose `run` is on another PC? Is the resume task's cadence
   change (every 2 minutes from 15:00 to 16:30) fine?
4. Does the cycle ping `IBKR_HEARTBEAT_URL` at start and at "ended", or only on each beat?
5. Trend: are `live/targets` and the export folder git-ignored (so the data sync carries them)? Which absolute paths
   are in `config/local.yaml`?
6. `IBKR_REPLICA_GTD` on the VPS: on or off?
7. Work item B (launcher default holder and automatic start): yours, or should VPS Claude build it?
8. Start of Day's peak memory from Monday's run.
