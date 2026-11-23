"""A daily task's run on the PC that holds the day, as the other PCs' pages show it (elsewhere.py; Stephen, 23 Nov
2026: "if desktop or laptop run the daily job the other 2 pc should show the updated daily status"). Run from the
launcher folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config import RemindConfig, TaskConfig
from elsewhere import Elsewhere, from_cycle, from_record
from machine_sync.daily import record_claim
from task_runner import TaskRunner

SYD = ZoneInfo("Australia/Sydney")
MONDAY = date(2026, 11, 23)  # its Start of Day decides Friday 20 Nov
NOW = datetime(2026, 11, 23, 18, 45, tzinfo=SYD)


class ElsewhereCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="elsewhere-"))
        self.records = self.tmp / "sod_{t}.json"
        self.prog = self.tmp / "sod_progress.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sod(self) -> TaskConfig:
        return TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim="daily", timezone="Australia/Sydney", progress_file=str(self.prog),
                          remind=RemindConfig(at=["11:00"], record=str(self.records)))

    def cycle(self) -> TaskConfig:
        return TaskConfig(id="cycle", label="IBKR paper cycle", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim="daily", claim_day="18:00 America/New_York", timezone="Australia/Sydney",
                          elsewhere_cmd=["prog", "day", "--day", "{day}"])

    def record(self, verdict: str, finished: str = "2026-11-22T23:30:43+00:00") -> None:
        Path(str(self.records).format(t="2026-11-20")).write_text(
            json.dumps({"verdict": verdict, "finished": finished}), encoding="utf-8")

    def progress(self, last: datetime, state: str = "running", t: str = "2026-11-20") -> None:
        self.prog.write_text(json.dumps({
            "schema": "sod_progress/1", "state": state, "decision_date": t, "step": 7, "steps": 16,
            "step_title": "Indicator QDF", "started_utc": (last - timedelta(minutes=20)).isoformat(),
            "last_output_utc": last.isoformat(),
        }), encoding="utf-8")

    # ----- Start of Day, from its record and progress file -----
    def test_a_go_record_is_done_with_its_time(self) -> None:
        self.record("GO")
        view = from_record(self.sod(), MONDAY, NOW, "vps")
        self.assertEqual(view, {"holder": "vps", "state": "done", "text": "Done on the vps at 10:30: GO"})

    def test_a_hold_record_is_failed_and_says_what_it_means(self) -> None:
        self.record("HOLD")
        view = from_record(self.sod(), MONDAY, NOW, "laptop")
        self.assertEqual(view["state"], "failed")
        self.assertTrue(view["text"].startswith("HOLD on the laptop at 10:30"))
        self.assertIn("yesterday's positions", view["text"])

    def test_a_run_in_progress_shows_its_step(self) -> None:
        self.progress(NOW - timedelta(minutes=2))
        view = from_record(self.sod(), MONDAY, NOW, "desktop")
        self.assertEqual(view, {"holder": "desktop", "state": "running",
                                "text": "Running on the desktop, step 7 of 16: Indicator QDF"})

    def test_a_progress_file_gone_quiet_is_stalled(self) -> None:
        self.progress(NOW - timedelta(minutes=40))
        view = from_record(self.sod(), MONDAY, NOW, "vps")
        self.assertEqual(view["state"], "stalled")
        self.assertIn("no news for 40 min", view["text"])

    def test_nothing_yet_or_an_older_days_progress_is_not_started(self) -> None:
        self.assertEqual(from_record(self.sod(), MONDAY, NOW, "vps")["state"], "todo")
        self.progress(NOW - timedelta(minutes=1), t="2026-11-19")  # last Thursday's run
        view = from_record(self.sod(), MONDAY, NOW, "vps")
        self.assertEqual(view, {"holder": "vps", "state": "todo", "text": "Not started on the vps yet"})

    # ----- the IBKR cycle, from IBKR's `day` command -----
    def cycle_answer(self, **c) -> dict:
        base = {"id": "2026-11-23-paper", "step": "execute", "status": "running", "updated_at": None,
                "approved_at": None, "approved_by": None, "halt": None}
        return {"day": "2026-11-23", "mode": "paper", "cycle": {**base, **c}}

    def test_cycle_states(self) -> None:
        task = self.cycle()
        self.assertEqual(from_cycle({"cycle": None}, task, "vps")["state"], "todo")
        waiting = from_cycle(self.cycle_answer(step="approve", status="waiting"), task, "vps")
        self.assertEqual(waiting["state"], "running")
        self.assertIn("Waiting for your approval on the vps", waiting["text"])
        trading = from_cycle(self.cycle_answer(approved_at="2026-11-23T04:02:22+00:00",
                                               approved_by="Stephen via Telegram"), task, "vps")
        self.assertEqual(trading, {"holder": "vps", "state": "running", "text":
                                   "Running on the vps: execute; approved by Stephen via Telegram at 15:02"})
        done = from_cycle(self.cycle_answer(step="report", status="done", updated_at="2026-11-23T21:21:00+00:00"),
                          task, "vps")
        self.assertEqual(done["state"], "done")
        self.assertIn("Done on the vps at 08:21", done["text"])
        halted = from_cycle(self.cycle_answer(status="halted", halt="gateway unreachable"), task, "laptop")
        self.assertEqual(halted, {"holder": "laptop", "state": "failed",
                                  "text": "Halted on the laptop at execute: gateway unreachable"})

    def test_the_command_gets_the_day_and_its_answer_is_cached(self) -> None:
        calls = []

        def run(cmd, cwd):
            calls.append(cmd)
            return "noise\n" + json.dumps(self.cycle_answer()) + "\n"

        ew = Elsewhere(run=run, ttl_s=60)
        first = ew.view(self.cycle(), "2026-11-23", MONDAY, "vps", wait=True)
        again = ew.view(self.cycle(), "2026-11-23", MONDAY, "vps", wait=True)
        self.assertEqual(first["text"], "Running on the vps: execute")
        self.assertEqual(again, first)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][-3:], ["day", "--day", "2026-11-23"])

    def test_a_command_that_fails_says_so_and_tries_again_later(self) -> None:
        def run(cmd, cwd):
            raise TimeoutError("database not reachable")

        ew = Elsewhere(run=run, ttl_s=0)
        view = ew.view(self.cycle(), "2026-11-23", MONDAY, "vps", wait=True)
        self.assertEqual(view["state"], "todo")
        self.assertIn("could not be read here (TimeoutError)", view["text"])

    # ----- the page's status: the same on every PC -----
    def runner_on(self, machine: str, holder: str | None) -> TaskRunner:
        sync = self.tmp / f"sync-{machine}"
        sync.mkdir(exist_ok=True)
        (sync / "machine.txt").write_text(f"{machine}\n")
        if holder:
            record_claim(sync, "daily", "2026-11-23", holder, "2026-11-23T09:30:00")
        return TaskRunner([self.sod()], self.tmp / f"logs-{machine}", claimer=lambda *a, **k: None, sync_dir=sync,
                          pruner=lambda: None, notify=lambda _: None)

    def test_each_pc_that_does_not_hold_the_day_shows_the_holders_run(self) -> None:
        self.record("GO")
        now = datetime(2026, 11, 23, 12, 0, tzinfo=SYD)
        for holder in ("vps", "desktop", "laptop"):
            for machine in ("vps", "desktop", "laptop"):
                item = self.runner_on(machine, holder).status(now)["tasks"][0]
                if machine == holder:
                    self.assertIsNone(item["elsewhere"], (machine, holder))
                else:
                    self.assertEqual(item["elsewhere"]["text"], f"Done on the {holder} at 10:30: GO", (machine, holder))

    def test_no_holder_yet_shows_nothing_elsewhere(self) -> None:
        item = self.runner_on("desktop", None).status(datetime(2026, 11, 23, 9, 0, tzinfo=SYD))["tasks"][0]
        self.assertIsNone(item["elsewhere"])


if __name__ == "__main__":
    unittest.main()
