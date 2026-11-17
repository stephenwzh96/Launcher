"""The Start of Day reminder (reminder.py). Run from the launcher folder:
.venv\\Scripts\\python.exe -m unittest discover tests"""
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


if __name__ == "__main__":
    unittest.main()
