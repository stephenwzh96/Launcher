"""The Start of Day reminder (reminder.py). Run from the launcher folder:
.venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest import mock

import progress
import reminder
from config import TaskConfig

SYDNEY = progress.zone("Australia/Sydney")


def sydney(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=SYDNEY)


TUE_1100 = sydney(2026, 11, 17, 11, 0)  # t = Mon 16 Nov


class DecisionDate(unittest.TestCase):
    def test_weekday_before(self):
        self.assertEqual(reminder.decision_date(date(2026, 11, 17)), date(2026, 11, 16))  # Tue -> Mon
        self.assertEqual(reminder.decision_date(date(2026, 11, 16)), date(2026, 11, 13))  # Mon -> Fri
        self.assertEqual(reminder.decision_date(date(2026, 11, 15)), date(2026, 11, 13))  # Sun -> Fri


class Due(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.task = TaskConfig(
            id="sod", label="MTFA Start of Day", cwd=".", cmd=["x"], timezone="Australia/Sydney",
            remind={"at": ["11:00", "12:30"], "record": str(self.root / "sod_{t}.json")},
        )  # fmt: skip

    def tearDown(self):
        self.dir.cleanup()

    def due(self, now=TUE_1100, running=False, prog=None, preview=""):
        return reminder.due(self.task, now, running, prog, preview)

    def test_times(self):
        self.assertIsNone(self.due(sydney(2026, 11, 17, 10, 59)))
        first = self.due()
        self.assertEqual((first["t"], first["slot"], first["again"]), ("2026-11-16", "11:00", False))
        self.assertEqual(first["text"], "MTFA Start of Day for Mon 16 Nov not started")
        second = self.due(sydney(2026, 11, 17, 12, 30))
        self.assertEqual((second["slot"], second["again"]), ("12:30", True))
        self.assertEqual(self.due(sydney(2026, 11, 17, 15, 0))["slot"], "12:30")  # stays until the record exists

    def test_sydney_time_whatever_the_machine(self):
        utc = datetime(2026, 11, 17, 0, 0, tzinfo=progress.zone("UTC"))  # 11:00 Sydney (AEDT)
        self.assertEqual(self.due(utc)["slot"], "11:00")

    def test_weekdays_only(self):
        self.assertIsNone(self.due(sydney(2026, 11, 21, 12, 0)))  # Saturday
        self.assertIsNone(self.due(sydney(2026, 11, 22, 12, 0)))  # Sunday
        monday = self.due(sydney(2026, 11, 16, 11, 0))
        self.assertEqual(monday["text"], "MTFA Start of Day for Fri 13 Nov not started")

    def test_none_once_the_record_exists(self):
        (self.root / "sod_2026-11-16.json").write_text("{}")
        self.assertIsNone(self.due())
        (self.root / "sod_2026-11-16.json").unlink()
        (self.root / "sod_2026-11-13.json").write_text("{}")  # an older day's record does not count
        self.assertIsNotNone(self.due())

    def test_none_while_it_runs(self):
        self.assertIsNone(self.due(running=True))
        prog = {"decision_date": "2026-11-16", "state": "running", "pid": 1, "started_utc": "2026-11-16T23:50:00Z"}
        with mock.patch("progress.pid_alive", return_value=True):
            self.assertIsNone(self.due(prog=prog))
            self.assertIsNotNone(self.due(prog={**prog, "decision_date": "2026-11-13"}))  # another day's run
            self.assertIsNotNone(self.due(prog={**prog, "state": "failed"}))
        with mock.patch("progress.pid_alive", return_value=False):
            self.assertIsNotNone(self.due(prog=prog))  # abandoned: not running after all

    def test_latest_start_from_the_plan(self):
        plan = "Decision date Mon 16 Nov, cut-off 14:30: Norgate has every market. Today: ... start by 13:25."
        self.assertEqual(
            self.due(preview=plan)["text"], "MTFA Start of Day for Mon 16 Nov not started; latest start 13:25"
        )
        self.assertIsNone(self.due(preview="Today: STANDARD download. About 900 MB, ~40 min of work.")["latest_start"])

    def test_bad_time_is_refused(self):
        with self.assertRaises(ValueError):
            TaskConfig(id="x", label="X", cwd=".", cmd=["x"], remind={"at": ["11h00"], "record": "r_{t}.json"})


class CycleReminder(unittest.TestCase):
    """The IBKR cycle's presses (team review, 20 Nov 2026, trade operations 4): the first press once Start of Day is
    GO, then the approval and Start trading; read from IBKR's heartbeat file."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        self.task = TaskConfig(
            id="ibkr-paper-cycle", label="IBKR paper cycle", cwd=".", cmd=["x"], timezone="Australia/Sydney",
            claim="daily", claim_day="18:00 America/New_York",
            remind={"at": ["15:00", "15:30", "15:50"], "heartbeat": str(self.root / "heartbeat.json"),
                    "go": str(self.root / "sod_{t}.json")},
        )  # fmt: skip
        self.go("GO")

    def tearDown(self):
        self.dir.cleanup()

    def go(self, verdict, t="2026-11-18"):
        (self.root / f"sod_{t}.json").write_text(json.dumps({"verdict": verdict, "day": t}))

    def beat(self, cycle_id="2026-11-19-paper", **fields):
        (self.root / "heartbeat.json").write_text(json.dumps({"cycle_id": cycle_id, **fields}))

    def due(self, now=sydney(2026, 11, 19, 15, 0), running=False, day="2026-11-19"):
        return reminder.due(self.task, now, running, None, "", day=day)

    def test_the_first_press_once_start_of_day_is_go(self):
        self.assertIsNone(self.due(sydney(2026, 11, 19, 14, 59)))
        first = self.due()
        self.assertEqual((first["stage"], first["t"], first["slot"], first["start"]), ("first", "2026-11-19", "15:00", True))
        self.assertEqual(first["text"], "IBKR paper cycle for Thu 19 Nov: Start of Day is GO, and the first press is not done")
        self.assertIn("before the first window (about 16:25 Sydney; 15:55 from April)", first["note"])
        self.assertTrue(self.due(sydney(2026, 11, 19, 15, 50))["again"])

    def test_nothing_before_go_or_on_a_hold(self):
        (self.root / "sod_2026-11-18.json").unlink()
        self.assertIsNone(self.due())  # Start of Day's own reminder stands
        self.go("HOLD")
        self.assertIsNone(self.due())

    def test_the_approval_after_a_first_press_that_ended_waiting(self):
        self.beat(run="ended", ended="waiting", step="approve", status="waiting")
        waiting = self.due(sydney(2026, 11, 19, 15, 30))
        self.assertEqual((waiting["stage"], waiting["start"]), ("approval", False))
        self.assertEqual(waiting["text"], "IBKR paper cycle for Thu 19 Nov: the list waits for your approval")
        self.assertIn("approve it on MTFA Operations, then press Start trading", waiting["note"])

    def test_nothing_while_a_run_beats_or_once_it_ended_otherwise(self):
        for fields in ({"run": "running", "status": "running"}, {"run": "connecting"},
                       {"run": "ended", "ended": "done"}, {"run": "ended", "ended": "halted"}):
            self.beat(**fields)
            self.assertIsNone(self.due(), fields)
        self.assertIsNone(self.due(running=True))  # the launcher is running a press

    def test_another_cycles_heartbeat_is_not_tonights(self):
        self.beat("2026-11-18-paper", run="ended", ended="done")
        self.assertEqual(self.due()["stage"], "first")

    def test_weekdays_only_and_the_trade_days_decision_date(self):
        self.assertIsNone(self.due(sydney(2026, 11, 21, 15, 30), day="2026-11-23"))  # Saturday
        self.go("GO", t="2026-11-20")
        monday = self.due(sydney(2026, 11, 23, 15, 0), day="2026-11-23")  # Monday's t is Friday
        self.assertEqual(monday["text"][:34], "IBKR paper cycle for Mon 23 Nov: S")

    def test_one_kind_of_reminder_per_task(self):
        with self.assertRaises(ValueError):
            TaskConfig(id="x", label="X", cwd=".", cmd=["x"], remind={"at": ["15:00"]})
        with self.assertRaises(ValueError):
            TaskConfig(id="x", label="X", cwd=".", cmd=["x"],
                       remind={"at": ["15:00"], "record": "r_{t}.json", "heartbeat": "h.json"})

    def test_the_runner_asks_for_the_claim_day(self):
        from task_runner import TaskRunner

        runner = TaskRunner([self.task], self.root / "logs", sync_dir=self.root / "MachineSync")
        due = runner.reminders({}, now=sydney(2026, 11, 19, 15, 0))
        self.assertEqual([d["t"] for d in due], ["2026-11-19"])


if __name__ == "__main__":
    unittest.main()
