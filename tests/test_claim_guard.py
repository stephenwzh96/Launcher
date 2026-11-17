"""The launcher starts a daily task (tasks.yaml `claim`) only after claiming the day; the claim itself is tested in
tests/msync/test_claims.py. Run from the launcher folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from config import RemindConfig, TaskConfig
from machine_sync.claims import ClaimResult
from task_runner import TaskRunner


class FakeClaimer:
    def __init__(self, result: ClaimResult | None = None) -> None:
        self.result, self.calls = result, []

    def __call__(self, task, day, machine, take_over):
        self.calls.append((task.id, day, machine, take_over))
        if self.result is None:
            raise AssertionError("no claim expected")
        return self.result


class ClaimGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="claimguard-"))
        self.sync_dir = self.tmp / "MachineSync"
        self.sync_dir.mkdir()
        (self.sync_dir / "machine.txt").write_text("desktop\n")

        self.runners: list[TaskRunner] = []

    def tearDown(self) -> None:
        for r in self.runners:
            for proc in r.procs.values():
                proc.wait(timeout=30)

    def runner(self, claimer, claim="daily", remind=None) -> TaskRunner:
        task = TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim=claim, remind=remind)
        self.runners.append(TaskRunner([task], self.tmp / "logs", claimer=claimer, sync_dir=self.sync_dir))
        return self.runners[-1]

    def test_daily_task_refused_when_other_pc_holds(self) -> None:
        r = self.runner(FakeClaimer(ClaimResult(False, "laptop", "2026-11-17T09:41:00")))
        err = r.start("sod")
        self.assertIn("already started on laptop at 09:41", err)
        self.assertNotIn("sod", r.runs)
        self.assertEqual(r.refusals["sod"], "laptop")

    def test_unreachable_refused(self) -> None:
        r = self.runner(FakeClaimer(ClaimResult(False, None, None, "Could not resolve host: github.com")))
        err = r.start("sod")
        self.assertIn("could not check GitHub", err)
        self.assertNotIn("sod", r.runs)

    def test_no_machine_name_refused(self) -> None:
        (self.sync_dir / "machine.txt").unlink()
        err = self.runner(FakeClaimer()).start("sod")
        self.assertIn("machine.txt", err)

    def test_claimed_task_starts_and_is_recorded(self) -> None:
        claimer = FakeClaimer(ClaimResult(True, "desktop", "2026-11-17T09:41:00"))
        r = self.runner(claimer)
        self.assertIsNone(r.start("sod"))
        self.assertEqual(r.runs["sod"]["state"], "running")
        claims = json.loads((self.sync_dir / "daily_claim.json").read_text())["claims"]
        self.assertEqual(claims[0]["holder"], "desktop")

    def test_task_without_claim_starts_without_check(self) -> None:
        r = self.runner(FakeClaimer(), claim=None)
        self.assertIsNone(r.start("sod"))

    def test_take_over_passed_through(self) -> None:
        claimer = FakeClaimer(ClaimResult(True, "desktop", "2026-11-17T10:05:00"))
        self.runner(claimer).start("sod", take_over=True)
        self.assertTrue(claimer.calls[0][3])

    def test_reminder_hidden_when_other_pc_holds_claim(self) -> None:
        remind = RemindConfig(at=["00:00"], record=str(self.tmp / "no_record_{t}.json"))
        r = self.runner(FakeClaimer(), remind=remind)
        wednesday_noon = datetime(2026, 11, 18, 12, 0).astimezone()
        self.assertTrue(r.reminders({}, now=wednesday_noon))
        (self.sync_dir / "daily_claim.json").write_text(json.dumps({"claims": [
            {"claim": "daily", "day": "2026-11-18", "holder": "laptop", "at": "2026-11-18T09:41:00"}]}))
        self.assertEqual(r.reminders({}, now=wednesday_noon), [])
