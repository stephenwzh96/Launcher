"""The launcher starts a daily task (tasks.yaml `claim`) only after claiming the day; the claim itself is tested in
tests/msync/test_claims.py. Run from the launcher folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from config import RemindConfig, TaskConfig
from machine_sync.claims import ClaimResult
from task_runner import TaskRunner, claim_day


class FakeClaimer:
    def __init__(self, result: ClaimResult | None = None) -> None:
        self.result, self.calls = result, []

    def __call__(self, task, day, machine, take_over, record=None):
        self.calls.append((task.id, day, machine, take_over))
        self.record = record
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

    def test_status_not_blocked_while_claiming(self) -> None:
        import threading
        import time

        class SlowClaimer(FakeClaimer):
            def __call__(self, task, day, machine, take_over, record=None):
                time.sleep(2)
                return ClaimResult(True, machine, "2026-11-17T09:41:00")

        r = self.runner(SlowClaimer())
        starter = threading.Thread(target=r.start, args=("sod",))
        starter.start()
        time.sleep(0.3)
        began = time.time()
        r.status()
        self.assertLess(time.time() - began, 1.0)
        starter.join()

    def test_waits_for_a_sync_run_then_refuses(self) -> None:
        import os

        (self.sync_dir / "run.lock").write_text(str(os.getpid()))  # a sync run in progress
        r = self.runner(FakeClaimer(ClaimResult(True, "desktop", "2026-11-17T09:41:00")))
        r.sync_wait_s = 0.5
        err = r.start("sod")
        self.assertIn("sync", err)
        self.assertNotIn("sod", r.runs)

    def test_sync_lock_released_after_start(self) -> None:
        r = self.runner(FakeClaimer(ClaimResult(True, "desktop", "2026-11-17T09:41:00")))
        self.assertIsNone(r.start("sod"))
        self.assertFalse((self.sync_dir / "run.lock").exists())

    def test_reminder_hidden_when_other_pc_holds_claim(self) -> None:
        remind = RemindConfig(at=["00:00"], record=str(self.tmp / "no_record_{t}.json"))
        r = self.runner(FakeClaimer(), remind=remind)
        wednesday_noon = datetime(2026, 11, 18, 12, 0).astimezone()
        self.assertTrue(r.reminders({}, now=wednesday_noon))
        (self.sync_dir / "daily_claim.json").write_text(json.dumps({"claims": [
            {"claim": "daily", "day": "2026-11-18", "holder": "laptop", "at": "2026-11-18T09:41:00"}]}))
        self.assertEqual(r.reminders({}, now=wednesday_noon), [])


class ClaimDayTest(unittest.TestCase):
    """The day a daily task claims is the day of the run the press belongs to: the IBKR paper cycle's second press
    or a restart after midnight Sydney stays on the day its cycle began (tasks.yaml `claim_day`), instead of taking
    the next day from the PC that runs that day's Start of Day."""
    SYDNEY = ZoneInfo("Australia/Sydney")
    US_CLOSE = "18:00 America/New_York"

    def task(self, rule: str | None = None) -> TaskConfig:
        return TaskConfig(id="paper", label="IBKR paper cycle", cwd=".", cmd=["x"], claim="daily",
                          timezone="Australia/Sydney", claim_day=rule)

    def at(self, *when: int) -> datetime:
        return datetime(*when, tzinfo=self.SYDNEY)

    def test_without_claim_day_the_task_claims_its_calendar_day(self) -> None:
        self.assertEqual(claim_day(self.task(), self.at(2026, 11, 19, 0, 30)), "2026-11-19")

    def test_press_after_midnight_stays_on_the_day_the_cycle_began(self) -> None:
        paper = self.task(self.US_CLOSE)
        self.assertEqual(claim_day(paper, self.at(2026, 11, 18, 16, 0)), "2026-11-18")  # Wednesday's first press
        self.assertEqual(claim_day(paper, self.at(2026, 11, 19, 0, 30)), "2026-11-18")  # restart after midnight
        self.assertEqual(claim_day(paper, self.at(2026, 11, 19, 8, 20)), "2026-11-18")  # the night's reconcile
        self.assertEqual(claim_day(paper, self.at(2026, 11, 19, 16, 0)), "2026-11-19")  # Thursday's first press

    def test_friday_night_and_monday(self) -> None:
        paper = self.task(self.US_CLOSE)
        self.assertEqual(claim_day(paper, self.at(2026, 11, 21, 1, 0)), "2026-11-20")  # Saturday 01:00: Friday's
        self.assertEqual(claim_day(paper, self.at(2026, 11, 23, 16, 0)), "2026-11-23")  # Monday's first press

    def test_us_summer_time(self) -> None:  # 18:00 New York is 08:00 Sydney in July
        paper = self.task(self.US_CLOSE)
        self.assertEqual(claim_day(paper, self.at(2026, 7, 16, 7, 30)), "2026-07-15")
        self.assertEqual(claim_day(paper, self.at(2026, 7, 16, 16, 0)), "2026-07-16")

    def test_same_day_as_start_of_day_on_every_weekday(self) -> None:
        paper, sod = self.task(self.US_CLOSE), self.task()
        for day in range(16, 21):  # Monday 16 to Friday 20 November
            self.assertEqual(claim_day(paper, self.at(2026, 11, day, 16, 0)),
                             claim_day(sod, self.at(2026, 11, day, 9, 30)))

    def test_bad_rule_refused_when_tasks_yaml_loads(self) -> None:
        for rule in ("18:00", "6pm America/New_York", "18:00 America/Nowhere"):
            with self.assertRaises(ValidationError, msg=rule):
                self.task(rule)


class AgainLabelTest(unittest.TestCase):
    """The page's button once today's run is done: "Rerun", or the task's `again_label` (the IBKR paper cycle's
    second press trades the approved list: "Start trading")."""

    def test_status_carries_the_label(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="again-"))
        paper = TaskConfig(id="paper", label="IBKR paper cycle", cwd=".", cmd=["x"], again_label="Start trading")
        sod = TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=["x"])
        tasks = {t["id"]: t for t in TaskRunner([paper, sod], tmp / "logs", sync_dir=tmp).status()["tasks"]}
        self.assertEqual(tasks["paper"]["again_label"], "Start trading")
        self.assertIsNone(tasks["sod"]["again_label"])


class RunAllRefusalTest(unittest.TestCase):
    """Run all stops at a refused start and leaves that refusal, with its offer, for the page (review of the branch,
    item 1): it never stops silently."""

    def test_refusal_is_shown_with_its_offer(self) -> None:
        import time

        tmp = Path(tempfile.mkdtemp(prefix="runall-"))
        sync_dir = tmp / "MachineSync"
        sync_dir.mkdir()
        (sync_dir / "machine.txt").write_text("desktop\n")
        sod = TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=[sys.executable, "-c", "pass"],
                         claim="daily")
        after = TaskConfig(id="after", label="Later", cwd=".", cmd=[sys.executable, "-c", "pass"])
        refused = FakeClaimer(ClaimResult(False, "laptop", "2026-11-18T09:41:00"))
        r = TaskRunner([sod, after], tmp / "logs", claimer=refused, sync_dir=sync_dir)
        self.assertIsNone(r.status()["run_all_refusal"])
        self.assertEqual(r.run_all(), ["sod", "after"])
        deadline = time.time() + 10
        while r.status()["running_all"] and time.time() < deadline:
            time.sleep(0.1)
        refusal = r.status()["run_all_refusal"]
        self.assertEqual((refusal["seq"], refusal["task_id"], refusal["offer"], refusal["claimed_by"]),
                         (1, "sod", "take_over", "laptop"))
        self.assertIn("already started on laptop", refusal["errors"][0])
        self.assertNotIn("after", r.runs)  # the queue stopped there


class PruneOffStartPathTest(unittest.TestCase):
    """Old claims are pruned after the task started, in the background and outside run.lock (review of 18 Nov, M9):
    a slow GitHub never holds a start, and a refused start prunes nothing."""

    def setUp(self) -> None:
        import threading

        self.tmp = Path(tempfile.mkdtemp(prefix="prune-"))
        self.sync_dir = self.tmp / "MachineSync"
        self.sync_dir.mkdir()
        (self.sync_dir / "machine.txt").write_text("desktop\n")
        self.pruned = threading.Event()
        self.seen: dict = {}

    def pruner(self) -> None:
        import threading

        self.seen["lock_file"] = (self.sync_dir / "run.lock").exists()
        self.seen["thread"] = threading.current_thread() is not threading.main_thread()
        self.pruned.set()

    def runner(self, result: ClaimResult) -> TaskRunner:
        task = TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim="daily")
        r = TaskRunner([task], self.tmp / "logs", claimer=FakeClaimer(result), sync_dir=self.sync_dir,
                       pruner=self.pruner)
        self.addCleanup(lambda: [p.wait(30) for p in r.procs.values()])
        return r

    def test_pruned_after_start_in_background_without_the_lock(self) -> None:
        self.assertIsNone(self.runner(ClaimResult(True, "desktop", "2026-11-18T09:41:00")).start("sod"))
        self.assertTrue(self.pruned.wait(10))
        self.assertEqual(self.seen, {"lock_file": False, "thread": True})

    def test_refused_start_prunes_nothing(self) -> None:
        self.runner(ClaimResult(False, "laptop", "2026-11-18T09:41:00")).start("sod")
        self.assertFalse(self.pruned.wait(0.5))

    def test_stand_in_claimer_never_prunes_on_github(self) -> None:
        from unittest import mock

        import task_runner

        task = TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim="daily")
        with mock.patch.object(task_runner, "_prune_on_github", side_effect=AssertionError("GitHub reached")) as real:
            r = TaskRunner([task], self.tmp / "logs", claimer=FakeClaimer(ClaimResult(True, "desktop", "x")),
                           sync_dir=self.sync_dir)
            self.addCleanup(lambda: [p.wait(30) for p in r.procs.values()])
            self.assertIsNone(r.start("sod"))
            import time
            time.sleep(0.5)
        real.assert_not_called()
