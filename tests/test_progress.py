"""The progress file (progress.py) and how the task runner matches it to a run. Run from the launcher folder:
.venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

import progress
from config import TaskConfig
from process_control import pid_alive
from task_runner import TaskRunner

SYDNEY = progress.zone("Australia/Sydney")
NOW = datetime(2026, 11, 17, 1, 0, tzinfo=UTC)  # 12:00 Sydney (AEDT)


def iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def sample(**over) -> dict:
    p = {
        "schema": "sod_progress/1", "pid": 4242, "decision_date": "2026-11-16", "state": "running",
        "step": 3, "steps": 17, "step_title": "Free sources",
        "started_utc": iso(NOW - timedelta(minutes=30)), "step_started_utc": iso(NOW - timedelta(minutes=5)),
        "last_output_utc": iso(NOW - timedelta(seconds=20)), "eta_utc": iso(NOW + timedelta(minutes=50)),
        "cutoff_local": "14:30", "deliver_by_local": "14:45", "on_battery": False, "log": "x.log",
    }  # fmt: skip
    p.update(over)
    return p


class View(unittest.TestCase):
    def view(self, alive=True, **over):
        with mock.patch("progress.pid_alive", return_value=alive):
            return progress.view(sample(**over), NOW, SYDNEY)

    def test_running(self):
        v = self.view()
        self.assertEqual(v["step"], {"k": 3, "n": 17, "title": "Free sources"})
        self.assertEqual(v["idle_min"], 0)
        self.assertEqual(v["eta"], "12:50")  # Sydney
        self.assertFalse(v["stalled"] or v["abandoned"] or v["late"] or v["on_battery"])

    def test_stalled_after_ten_minutes_without_output(self):
        self.assertFalse(self.view(last_output_utc=iso(NOW - timedelta(minutes=9, seconds=59)))["stalled"])
        v = self.view(last_output_utc=iso(NOW - timedelta(minutes=14)))
        self.assertTrue(v["stalled"])
        self.assertEqual(v["idle_min"], 14)

    def test_only_a_running_file_stalls(self):
        self.assertFalse(self.view(state="done", last_output_utc=iso(NOW - timedelta(hours=2)))["stalled"])

    def test_abandoned_when_the_process_is_gone(self):
        v = self.view(alive=False, last_output_utc=iso(NOW - timedelta(minutes=40)))
        self.assertTrue(v["abandoned"])
        self.assertFalse(v["stalled"] or v["late"])
        self.assertFalse(self.view(alive=False, state="stopped")["abandoned"])

    def test_late_when_the_eta_is_after_deliver_by(self):
        self.assertFalse(self.view(eta_utc=iso(datetime(2026, 11, 17, 3, 45, tzinfo=UTC)))["late"])  # 14:45
        v = self.view(eta_utc=iso(datetime(2026, 11, 17, 3, 52, tzinfo=UTC)))
        self.assertEqual(v["eta"], "14:52")
        self.assertTrue(v["late"])

    def test_late_when_still_running_past_deliver_by(self):
        with mock.patch("progress.pid_alive", return_value=True):
            later = datetime(2026, 11, 17, 4, 0, tzinfo=UTC)  # 15:00 Sydney
            self.assertTrue(progress.view(sample(eta_utc=None, last_output_utc=iso(later)), later, SYDNEY)["late"])

    def test_missing_fields(self):
        v = self.view(eta_utc=None, step=None, last_output_utc=None, step_started_utc=None)
        self.assertIsNone(v["eta"])
        self.assertIsNone(v["step"])
        self.assertEqual(v["idle_min"], 30)  # from started_utc

    def test_read(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "p.json"
            self.assertIsNone(progress.read(path))
            path.write_text("{not json")
            self.assertIsNone(progress.read(path))
            path.write_text(json.dumps(sample(schema="other/1")))
            self.assertIsNone(progress.read(path))
            path.write_text(json.dumps(sample()))
            self.assertEqual(progress.read(path)["step"], 3)


class PidAlive(unittest.TestCase):
    def test_this_process(self):
        self.assertTrue(pid_alive(os.getpid()))
        self.assertTrue(pid_alive(os.getpid(), datetime.now(UTC)))
        # a process created after the time asked about is not the one that was running then (a reused pid)
        self.assertFalse(pid_alive(os.getpid(), datetime.now(UTC) - timedelta(days=30)))

    def test_ended_process(self):
        proc = subprocess.Popen([sys.executable, "-c", "pass"])
        proc.wait()
        self.assertFalse(pid_alive(proc.pid))
        self.assertFalse(pid_alive(0))
        self.assertFalse(pid_alive(None))


class RunnerMatch(unittest.TestCase):
    """A progress file shows on a run only when it started while that run was going."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        root = Path(self.dir.name)
        self.file = root / "sod_progress.json"
        task = TaskConfig(id="sod", label="SOD", cwd=".", cmd=["x"], progress_file=str(self.file),
                          timezone="Australia/Sydney")  # fmt: skip
        self.runner = TaskRunner([task], root / "logs")
        self.runner.runs["sod"] = {
            "state": "running", "started": "2026-11-17T11:30:00", "started_utc": "2026-11-17T00:30:00+00:00",
            "finished": None, "exit_code": None, "pid": os.getpid(), "log": "sod.log",
        }  # fmt: skip

    def tearDown(self):
        self.dir.cleanup()

    def status(self, **over):
        self.file.write_text(json.dumps(sample(**over)))
        with mock.patch("progress.pid_alive", return_value=True), mock.patch("task_runner.pid_alive", return_value=True):
            return self.runner.status(now=NOW)["tasks"][0]["run"]

    def test_this_runs_file(self):
        run = self.status()
        self.assertEqual(run["state"], "running")
        self.assertEqual(run["progress"]["eta"], "12:50")
        self.assertEqual(run["step"], {"k": 3, "n": 17, "title": "Free sources"})

    def test_an_earlier_runs_file_is_ignored(self):
        run = self.status(started_utc="2026-11-16T23:00:00+00:00", step=17)
        self.assertIsNone(run["progress"])
        self.assertIsNone(run["step"])

    def test_no_file(self):
        with mock.patch("task_runner.pid_alive", return_value=True):
            self.assertIsNone(self.runner.status(now=NOW)["tasks"][0]["run"]["progress"])


if __name__ == "__main__":
    unittest.main()
