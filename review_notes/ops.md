# Builder "ops": README text for the team review of 20 Nov 2026 (launcher)

Workstream: one person can run the day for months without a missed day or a silent failure. Each section says where it
belongs in `README.md` and is written as it should read there. IBKR's side is in IBKR's `review_notes/ops.md`.

---

## 1. `README.md`, "Start of Day tasks": after the **Reminder** bullet

- **The IBKR cycle's reminder** (team review, 20 Nov 2026, trade operations 4: the day side told nobody when a press was
  forgotten). The cycle has two presses and an approval between them, and leaves no record file until its night is
  over, so its `remind` names IBKR's heartbeat file instead of a `record`:

  ```yaml
    timezone: Australia/Sydney
    remind:
      at: ["15:00", "15:30", "15:50"]
      heartbeat: ../IBKR/logs/heartbeat.json   # IBKR's IBKR_HEARTBEAT_FILE on this PC: change both together
      go: ../Trend/AIJPMT1A_build/data/logs/sod_{t}.json
  ```

  On a weekday from the first `at` time, once Start of Day's record for the trade day's decision date says GO
  (before that, Start of Day's own reminder stands; on a HOLD there is nothing to press), the banner says
  "IBKR paper cycle for Thu 19 Nov: Start of Day is GO, and the first press is not done" while the heartbeat shows no
  run for the trade day's cycle, with a Start button; and "... the list waits for your approval" while that cycle's
  last run ended `waiting`, with no Start button (approve on MTFA Operations first, then press Start trading). No
  banner while the launcher runs a press, while a run for the cycle beats (started here or elsewhere), or once its run
  ended any other way (done, halted: the cycle's own Telegram alert says what to do). The trade day is the task's
  claim day (`claim_day`), so the banner names the cycle a press would run. Like Start of Day's, it is a banner while
  the page is open; the phone hears from the cycle itself (waiting, halted, the morning summary) and from IBKR's resume
  task.

## 2. `README.md`, "One PC per day": replaces "GitHub unreachable or the sync tool not installed (`MachineSync\machine.txt`): not started."

  The sync tool not installed (`MachineSync\machine.txt`): not started. **GitHub unreachable** (team review, 20 Nov
  2026, trade operations 9, architect 3: GitHub was a hard dependency of every press): IBKR's run lock now refuses a
  second run of a book in the book's own database, whoever starts it. So a PC that is the day's recorded holder
  (`MachineSync\daily_claim.json`: it claimed the day earlier, or its sync saw it hold the day) starts anyway, and the
  run's row says "Started with: GitHub could not be reached (...), so the day's claim was not checked there ...". Any
  other PC is refused, and the page offers **Start without the claim** with a plain warning: only if the other PC is
  off or is not running the day's daily tasks (nothing stops a second Start of Day on the other PC). Starting without
  the claim records this PC as the day's holder in `daily_claim.json` and says so on the row; once GitHub answers
  again the next press claims the day there as usual (a holder already on GitHub is still refused).

## 3. `README.md`, "Testing": add

The trade-day rule's copies (`task_runner.claim_day` for the IBKR cycle, `reminder.decision_date`) are tested against
IBKR's `reference/trade_day_cases.json` (`tests/test_trade_day_cases.py`); `tests/trade_day_cases.json` is this repo's
copy, for CI and a checkout without IBKR beside it, and a test fails when it differs from IBKR's. When IBKR's table
changes, copy it over.

CI (`.github/workflows/ci.yml`, team review developer 3): every push runs `python -m unittest discover tests` on
Windows from `requirements.lock.txt`.

## 4. `README.md`, "How it works": the `reminder.py` line

- `reminder.py` — whether a task's reminder is due: Start of Day's (a record for the day), and the IBKR cycle's two
  presses (its heartbeat, after Start of Day's GO).

## 5. For the lead (not for a document)

- Files: `config.py` (`RemindConfig` gains `heartbeat`, `go`, `mode`; `record` optional; exactly one of `record` or
  `heartbeat`), `reminder.py` (`cycle_due`; `due(..., day=)`), `task_runner.py` (`reminders` passes the claim day;
  `_check_claim` and `start(..., without_claim=)`), `app.py` (`without_claim` on the start endpoint), `static/index.html`
  (the banner's `note`, `start` and `tab`; the `start_without_claim` offer), `tasks.yaml` (the IBKR cycle's `timezone`
  and `remind`), tests, `.github/workflows/ci.yml`.
- The page shows the new banner from Monday 15:00 Sydney if this branch is merged: it reads `../IBKR/logs/heartbeat.json`.
  If a PC's `.env` moves `IBKR_HEARTBEAT_FILE`, change `remind.heartbeat` with it (a missing file reads as "first press
  not done").
- `machine_sync/claims.py` was not changed: the fallback is the launcher's decision on a failed claim, in
  `task_runner.py`.
