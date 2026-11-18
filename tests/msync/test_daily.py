import json
import os
from datetime import datetime
from pathlib import Path

from machine_sync.daily import (busy_repos, code_frozen, holds_claim_today, load_daily_tasks, record_claim,
                                running_tasks, venvs_in_use)
from machine_sync.procs import Proc, processes
from machine_sync.settings import Settings
from msync.helpers import TempDirCase


class DailyTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.cfg = Settings(home=self.tmp, machine="desktop")
        h = self.tmp
        self.ibkr = {"id": "ibkr-paper-cycle", "claim": "daily", "cwd": str(h / "IBKR"),
                     "cmd": [str(h / "IBKR" / ".venv" / "Scripts" / "python.exe"), "-m", "src.operations", "run",
                             "--mode", "paper", "--envelopes", str(h / "Trend" / "AIJPMT1A_build" / "live" / "targets")]}
        self.sod = {"id": "aijpmt1a-refresh", "claim": "daily", "cwd": str(h / "Trend" / "AIJPMT1A_build"),
                    "cmd": [str(h / "Trend" / "AIJPMT1A_build" / ".venv" / "Scripts" / "python.exe"),
                            str(h / "Trend" / "AIJPMT1A_build" / "tools" / "daily_cycle.py")]}

    def test_busy_repos_from_cwd_and_cmd(self) -> None:
        self.assertEqual(busy_repos(self.cfg, [self.ibkr]), {"IBKR", "Trend"})
        self.assertEqual(busy_repos(self.cfg, [self.sod]), {"Trend"})

    def test_running_matches_command_line(self) -> None:
        h = str(self.tmp)
        cycle = Proc(10, f"{h}\\IBKR\\.venv\\Scripts\\python.exe",
                     f'"{h}\\IBKR\\.venv\\Scripts\\python.exe" -m src.operations run --mode paper --envelopes '
                     f'{h}\\Trend\\AIJPMT1A_build\\live\\targets')
        status = Proc(11, f"{h}\\IBKR\\.venv\\Scripts\\python.exe",
                      f'"{h}\\IBKR\\.venv\\Scripts\\python.exe" -m src.operations status')
        self.assertEqual(running_tasks([self.ibkr, self.sod], [cycle, status]), {"ibkr-paper-cycle"})
        self.assertEqual(running_tasks([self.ibkr, self.sod], [status]), set())

    def test_code_frozen_until_nine_next_day(self) -> None:
        record_claim(self.cfg.sync_dir, "daily", "2026-11-17", "desktop", "2026-11-17T09:41:00")
        self.assertFalse(code_frozen(self.cfg, datetime(2026, 11, 17, 9, 0)))
        self.assertTrue(code_frozen(self.cfg, datetime(2026, 11, 17, 23, 0)))
        self.assertTrue(code_frozen(self.cfg, datetime(2026, 11, 18, 8, 59)))
        self.assertFalse(code_frozen(self.cfg, datetime(2026, 11, 18, 9, 0)))

    def test_only_daily_task_claims_freeze_code(self) -> None:
        record_claim(self.cfg.sync_dir, "e2e-test", "2026-11-17", "desktop", "2026-11-17T09:41:00")
        self.assertFalse(code_frozen(self.cfg, datetime(2026, 11, 17, 23, 0), names={"daily"}))
        self.assertFalse(holds_claim_today(self.cfg, datetime(2026, 11, 17, 23, 0), names={"daily"}))
        record_claim(self.cfg.sync_dir, "daily", "2026-11-17", "desktop", "2026-11-17T09:41:00")
        self.assertTrue(code_frozen(self.cfg, datetime(2026, 11, 17, 23, 0), names={"daily"}))

    def test_not_frozen_when_other_pc_holds_claim(self) -> None:
        record_claim(self.cfg.sync_dir, "daily", "2026-11-17", "laptop", "2026-11-17T09:41:00")
        self.assertFalse(code_frozen(self.cfg, datetime(2026, 11, 17, 23, 0)))
        self.assertFalse(holds_claim_today(self.cfg, datetime(2026, 11, 17, 23, 0)))

    def test_holds_claim_today(self) -> None:
        self.assertFalse(holds_claim_today(self.cfg, datetime(2026, 11, 17, 10, 0)))
        record_claim(self.cfg.sync_dir, "daily", "2026-11-17", "desktop", "2026-11-17T09:41:00")
        self.assertTrue(holds_claim_today(self.cfg, datetime(2026, 11, 17, 10, 0)))
        self.assertFalse(holds_claim_today(self.cfg, datetime(2026, 11, 18, 10, 0)))

    def test_record_claim_keeps_recent_days_only(self) -> None:
        for day in ("2026-11-10", "2026-11-16", "2026-11-17"):
            record_claim(self.cfg.sync_dir, "daily", day, "desktop", f"{day}T09:41:00")
        doc = json.loads((self.cfg.sync_dir / "daily_claim.json").read_text())
        self.assertEqual([c["day"] for c in doc["claims"]], ["2026-11-16", "2026-11-17"])

    def test_venv_in_use(self) -> None:
        exe = self.tmp / "Trend" / ".venv" / "Scripts" / "python.exe"
        procs = [Proc(5, str(exe), f'"{exe}" app.py'), Proc(6, None, "")]
        self.assertEqual(venvs_in_use(procs), {(self.tmp / "Trend" / ".venv").resolve()})

    def test_falls_back_to_last_dump(self) -> None:
        self.cfg.sync_dir.mkdir(parents=True)
        (self.cfg.sync_dir / "tasks.json").write_text(json.dumps([self.sod]))
        self.assertEqual(load_daily_tasks(self.cfg), [self.sod])  # no launcher venv in this home

    def test_processes_lists_this_process(self) -> None:
        self.assertIn(os.getpid(), {p.pid for p in processes()})

    def test_running_started_from_a_terminal(self) -> None:
        """A daily job started by hand (relative paths, another folder) is running too (review of 18 Nov, H4)."""
        sod = Proc(20, None, r'"C:\Python312\python.exe" tools\daily_cycle.py')
        sod_unix = Proc(21, None, "python ./tools/daily_cycle.py --day 2026-11-18")
        cycle = Proc(22, None, "python -m src.operations run --mode paper --envelopes ../Trend/AIJPMT1A_build/live/targets")
        status = Proc(23, None, "python -m src.operations status")
        editor = Proc(24, None, r'"C:\Program Files\Notepad++\notepad++.exe" C:\Users\User\Trend\AIJPMT1A_build\tools\daily_cycle.py')
        tasks = [self.ibkr, self.sod]
        self.assertEqual(running_tasks(tasks, [sod]), {"aijpmt1a-refresh"})
        self.assertEqual(running_tasks(tasks, [sod_unix]), {"aijpmt1a-refresh"})
        self.assertEqual(running_tasks(tasks, [cycle]), {"ibkr-paper-cycle"})
        self.assertEqual(running_tasks(tasks, [status, editor]), set())

    def test_running_from_progress_file(self) -> None:
        progress = self.tmp / "Trend" / "AIJPMT1A_build" / "data" / "logs" / "sod_progress.json"
        progress.parent.mkdir(parents=True)
        sod = {**self.sod, "progress_file": str(progress)}
        other = Proc(4321, None, "python something_else.py")
        progress.write_text(json.dumps({"schema": "sod_progress/1", "state": "running", "pid": 4321}))
        self.assertEqual(running_tasks([sod], [other]), {"aijpmt1a-refresh"})
        self.assertEqual(running_tasks([sod], []), set())  # its process is gone: abandoned, not running
        progress.write_text(json.dumps({"schema": "sod_progress/1", "state": "done", "pid": 4321}))
        self.assertEqual(running_tasks([sod], [other]), set())
        self.assertEqual(running_tasks([self.sod], [other]), set())  # a dump from before progress_file was listed

    def test_dump_lists_progress_file(self) -> None:
        import subprocess
        import sys

        from machine_sync.daily import _DUMP

        launcher = Path(__file__).resolve().parents[2]  # this checkout's tasks.yaml, read through its config.py
        done = subprocess.run([sys.executable, "-I", "-c", _DUMP], cwd=launcher, capture_output=True, text=True)
        tasks = {t["id"]: t for t in json.loads(done.stdout)}
        self.assertTrue(tasks["aijpmt1a-refresh"]["progress_file"].endswith("sod_progress.json"))
        self.assertIsNone(tasks["ibkr-paper-cycle"]["progress_file"])
