"""The automatic start (tasks.yaml `auto`; three-machine design, 20 Nov 2026: the VPS runs the day) and "Run today
here". Run from the launcher folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from config import AUTO_SWITCH, AutoConfig, RemindConfig, TaskConfig
from machine_sync.claims import ClaimResult
from machine_sync.daily import read_claims, record_claim
from task_runner import TaskRunner, claim_day

SYD = ZoneInfo("Australia/Sydney")
MONDAY = datetime(2026, 11, 23, tzinfo=SYD)  # its Start of Day decides Friday 20 Nov


class FakeClaimer:
    def __init__(self, result: ClaimResult) -> None:
        self.result, self.calls = result, []

    def __call__(self, task, day, machine, take_over, record=None):
        self.calls.append({"task": task.id, "day": day, "machine": machine, "take_over": take_over, "record": record})
        return self.result


class AutoStartCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="autostart-"))
        self.sync_dir = self.tmp / "MachineSync"
        self.sync_dir.mkdir()
        self.machine("vps")
        (self.sync_dir / AUTO_SWITCH).write_text("on\n")
        self.records = self.tmp / "sod_{t}.json"
        self.heartbeat = self.tmp / "heartbeat.json"
        self.told: list[str] = []
        self.runners: list[TaskRunner] = []

    def tearDown(self) -> None:
        for r in self.runners:
            for proc in r.procs.values():
                proc.wait(timeout=30)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def machine(self, name: str) -> None:
        (self.sync_dir / "machine.txt").write_text(f"{name}\n")

    def sod(self) -> TaskConfig:
        return TaskConfig(id="sod", label="MTFA Start of Day", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim="daily", timezone="Australia/Sydney",
                          remind=RemindConfig(at=["11:00"], record=str(self.records)),
                          auto=AutoConfig(pc="vps", at="09:30"))

    def cycle(self) -> TaskConfig:
        return TaskConfig(id="cycle", label="IBKR paper cycle", cwd=".", cmd=[sys.executable, "-c", "pass"],
                          claim="daily", claim_day="18:00 America/New_York", timezone="Australia/Sydney",
                          remind=RemindConfig(at=["15:30"], heartbeat=str(self.heartbeat), go=str(self.records)),
                          auto=AutoConfig(pc="vps", at="15:00"))

    def runner(self, claimer, *tasks) -> TaskRunner:
        r = TaskRunner(list(tasks) or [self.sod()], self.tmp / "logs", claimer=claimer, sync_dir=self.sync_dir,
                       pruner=lambda: None, notify=self.told.append)
        self.runners.append(r)
        return r

    @staticmethod
    def ok(machine: str = "vps") -> FakeClaimer:
        return FakeClaimer(ClaimResult(True, machine, datetime.now().isoformat(timespec="seconds")))


class AutoStartTest(AutoStartCase):
    def test_starts_from_its_time_on_its_pc_once(self) -> None:
        claimer = self.ok()
        r = self.runner(claimer)
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=9, minute=20)), [])
        self.assertEqual(claimer.calls, [])
        said = r.auto_tick(MONDAY.replace(hour=9, minute=35))
        self.assertEqual(said, ["MTFA Start of Day on the vps: started by itself at 09:35"])
        self.assertEqual(r.runs["sod"]["state"], "running")
        self.assertEqual(self.told, said)
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=9, minute=40)), [])  # once a day, even after it ends
        self.assertEqual(len(claimer.calls), 1)
        again = self.runner(claimer)  # a launcher restart remembers the day
        self.assertEqual(again.auto_tick(MONDAY.replace(hour=9, minute=45)), [])

    def test_never_on_another_pc(self) -> None:
        self.machine("desktop")
        r = self.runner(self.ok("desktop"))
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=9, minute=35)), [])
        self.assertFalse(r.status(MONDAY)["tasks"][0]["auto"]["armed"])

    def test_never_without_the_switch(self) -> None:
        (self.sync_dir / AUTO_SWITCH).unlink()
        r = self.runner(self.ok())
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=9, minute=35)), [])
        auto = r.status(MONDAY)["tasks"][0]["auto"]
        self.assertEqual((auto["pc"], auto["at"], auto["armed"]), ("vps", "09:30", False))

    def test_a_day_another_pc_holds_is_left_to_it(self) -> None:
        record_claim(self.sync_dir, "daily", "2026-11-23", "laptop", "2026-11-23T08:10:00")  # "Run today here" there
        claimer = self.ok()
        r = self.runner(claimer)
        said = r.auto_tick(MONDAY.replace(hour=9, minute=35))
        self.assertEqual(said, ["MTFA Start of Day on the vps: 2026-11-23 is the laptop's: not started here"])
        self.assertEqual(claimer.calls, [])
        self.assertNotIn("sod", r.runs)
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=10)), [])  # left for the day

    def test_claim_refused_on_github_is_left(self) -> None:
        r = self.runner(FakeClaimer(ClaimResult(False, "desktop", "2026-11-23T09:31:00")))
        said = r.auto_tick(MONDAY.replace(hour=9, minute=35))
        self.assertIn("is the desktop's: not started here", said[0])
        self.assertNotIn("sod", r.runs)

    def test_github_unreachable_tries_again_later_and_tells_once(self) -> None:
        claimer = FakeClaimer(ClaimResult(False, None, None, "Could not resolve host: github.com"))
        r = self.runner(claimer)
        first = MONDAY.replace(hour=9, minute=35)
        said = r.auto_tick(first)
        self.assertIn("could not start by itself at 09:35, tries again in 5 minutes", said[0])
        self.assertEqual(r.offers["sod"], "start_without_claim")  # never taken by itself
        self.assertEqual(r.auto_tick(first + timedelta(minutes=2)), [])
        self.assertEqual(len(r.auto_tick(first + timedelta(minutes=6))), 1)
        self.assertEqual(len(claimer.calls), 2)
        self.assertEqual(len(self.told), 1)  # told once, not every five minutes
        claimer.result = ClaimResult(True, "vps", "2026-11-23T09:47:00")
        self.assertIn("started by itself", r.auto_tick(first + timedelta(minutes=12))[0])

    def test_not_when_the_day_is_already_done(self) -> None:
        Path(str(self.records).format(t="2026-11-20")).write_text("{}")  # Monday's record (decides Friday)
        r = self.runner(self.ok())
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=9, minute=35)), [])

    def test_not_at_the_weekend(self) -> None:
        r = self.runner(self.ok())
        self.assertEqual(r.auto_tick(datetime(2026, 11, 21, 9, 35, tzinfo=SYD)), [])


class AutoCycleTest(AutoStartCase):
    def test_first_press_only_once_start_of_day_says_go(self) -> None:
        claimer = self.ok()
        r = self.runner(claimer, self.cycle())
        at = MONDAY.replace(hour=15, minute=5)
        self.assertEqual(claim_day(self.cycle(), at), "2026-11-23")
        self.assertEqual(r.auto_tick(at), [])  # no Start of Day record yet
        Path(str(self.records).format(t="2026-11-20")).write_text(json.dumps({"verdict": "HOLD"}))
        self.assertEqual(r.auto_tick(at), [])  # held: nothing to press
        Path(str(self.records).format(t="2026-11-20")).write_text(json.dumps({"verdict": "GO"}))
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=14, minute=50)), [])  # before its time
        self.assertIn("started by itself at 15:05", r.auto_tick(at)[0])

    def test_never_the_second_press(self) -> None:
        Path(str(self.records).format(t="2026-11-20")).write_text(json.dumps({"verdict": "GO"}))
        self.heartbeat.write_text(json.dumps({"cycle_id": "2026-11-23-paper", "run": "ended", "ended": "waiting"}))
        claimer = self.ok()
        r = self.runner(claimer, self.cycle())
        self.assertEqual(r.auto_tick(MONDAY.replace(hour=15, minute=40)), [])  # waits for the approval
        self.assertEqual(claimer.calls, [])


class RunTodayHereTest(AutoStartCase):
    def setUp(self) -> None:
        super().setUp()
        self.machine("desktop")

    def test_claims_today_for_this_pc_without_starting(self) -> None:
        claimer = self.ok("desktop")
        r = self.runner(claimer)
        err, day = r.reserve()
        self.assertIsNone(err)
        today = datetime.now(SYD).strftime("%Y-%m-%d")
        self.assertEqual(day, today)
        self.assertEqual(claimer.calls[0]["take_over"], False)
        self.assertEqual(claimer.calls[0]["record"], ["reserved by hand on desktop: nothing started"])
        self.assertEqual([(c["day"], c["holder"]) for c in read_claims(self.sync_dir)], [(today, "desktop")])
        self.assertNotIn("sod", r.runs)
        self.assertEqual(r.status()["day"], {"day": today, "holder": "desktop", "here": "desktop"})

    def test_a_later_day_freezes_code_only_from_that_day(self) -> None:
        r = self.runner(self.ok("desktop"))
        later = (datetime.now(SYD) + timedelta(days=3)).strftime("%Y-%m-%d")
        self.assertEqual(r.reserve(later), (None, later))
        claim = next(c for c in read_claims(self.sync_dir) if c["day"] == later)
        self.assertEqual(claim["at"], f"{later}T00:00:00")

    def test_refused_when_another_pc_holds_the_day(self) -> None:
        r = self.runner(FakeClaimer(ClaimResult(False, "vps", "2026-11-23T09:30:05")))
        err, _ = r.reserve()
        self.assertIn("already the vps's", err)
        self.assertIn("take it over", err)

    def test_refused_past_days_and_bad_dates_and_github_down(self) -> None:
        r = self.runner(FakeClaimer(ClaimResult(False, None, None, "timed out")))
        self.assertIn("has passed", r.reserve("2020-01-06")[0])
        self.assertIn("is not a date", r.reserve("next monday")[0])
        self.assertIn("could not reach GitHub (timed out): nothing reserved", r.reserve()[0])


class AutoConfigTest(unittest.TestCase):
    def test_auto_needs_a_claim_and_a_reminder_and_a_known_pc(self) -> None:
        with self.assertRaises(ValidationError):
            TaskConfig(id="x", label="x", cwd=".", cmd=["x"], auto=AutoConfig(pc="vps", at="09:30"))
        with self.assertRaises(ValidationError):
            AutoConfig(pc="nas", at="09:30")
        with self.assertRaises(ValidationError):
            AutoConfig(pc="vps", at="half past nine")

    def test_the_real_tasks_file_starts_both_daily_tasks_on_the_vps(self) -> None:
        from config import load_tasks

        tasks = {t.id: t for t in load_tasks(Path(__file__).resolve().parent.parent / "tasks.yaml")}
        self.assertEqual((tasks["aijpmt1a-refresh"].auto.pc, tasks["aijpmt1a-refresh"].auto.at), ("vps", "09:30"))
        self.assertEqual((tasks["ibkr-paper-cycle"].auto.pc, tasks["ibkr-paper-cycle"].auto.at), ("vps", "15:00"))
