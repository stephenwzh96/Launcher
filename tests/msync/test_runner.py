import json
import os
from datetime import datetime, timedelta

from machine_sync.__main__ import main
from machine_sync.gitops import read_repo
from machine_sync.install import install, task_xml
from machine_sync.runner import run_once
from msync.helpers import TempDirCase, commit, run, syncthing, two_pcs


class RunnerTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.desk, self.lap = two_pcs(self.tmp, ("Trend",))
        self.dt = self.desk.repo_path("Trend")
        self.lt = self.lap.repo_path("Trend")

    def run_pc(self, cfg, now: datetime | None = None, **kw) -> str:
        return run_once(cfg, now=now or datetime.now() + timedelta(minutes=5), procs=[], tasks=[], **kw)

    def test_status_shows_when_peer_last_ran(self) -> None:
        first = datetime.now() + timedelta(minutes=5)
        later = first + timedelta(minutes=10)
        self.run_pc(self.desk, now=first)
        syncthing(self.desk, self.lap)
        self.run_pc(self.lap, now=first)
        self.run_pc(self.lap, now=later)  # nothing changed: only the alive file moves on
        syncthing(self.lap, self.desk)
        self.assertIn(f"laptop last ran {later:%d %b %H:%M}", self.run_pc(self.desk, now=later))

    def test_two_pc_round_trip(self) -> None:
        import time
        time.sleep(1.1)
        run(self.lt, "switch", "-c", "feature")
        head = commit(self.lt, "f.txt", "f")
        run(self.lt, "push", "-u", "origin", "feature")
        (self.lt / "data").mkdir()
        (self.lt / "data" / "prices.csv").write_text("1,2,3")
        self.run_pc(self.desk)  # first runs: each PC learns what the other has
        syncthing(self.desk, self.lap)
        self.run_pc(self.lap)
        syncthing(self.lap, self.desk)
        text = self.run_pc(self.desk)
        self.assertEqual((read_repo(self.dt).branch, read_repo(self.dt).head), ("feature", head))
        self.assertEqual((self.dt / "data" / "prices.csv").read_text(), "1,2,3")
        self.assertIn("same as laptop", text)
        self.assertIn("took 1", text)
        self.assertEqual(text, (self.desk.sync_dir / "sync_status.txt").read_text(encoding="utf-8"))

    def test_status_lists_peer_unpushed(self) -> None:
        commit(self.lt, "u.txt", "unpushed")
        self.run_pc(self.lap)
        syncthing(self.lap, self.desk)
        self.assertIn("laptop has 1 unpushed commit", self.run_pc(self.desk))

    def test_peer_note_newer_format_stops_import(self) -> None:
        state = self.desk.home / "TripSync" / "_state"
        state.mkdir(parents=True)
        (self.desk.home / "TripSync" / "Trend" / "data").mkdir(parents=True)
        (self.desk.home / "TripSync" / "Trend" / "data" / "x.csv").write_text("x")
        (state / "laptop.json").write_text(json.dumps({"format": 99, "machine": "laptop", "written": 0,
                                                       "files": {"Trend/data/x.csv": ["0", 1, "laptop", None, False]}}))
        text = self.run_pc(self.desk)
        self.assertFalse((self.dt / "data" / "x.csv").exists())
        self.assertIn("newer sync tool", text)

    def test_lock_skips_overlapping_run(self) -> None:
        self.desk.sync_dir.mkdir(parents=True)
        (self.desk.sync_dir / "run.lock").write_text(str(os.getpid()))
        self.assertIn("still going", self.run_pc(self.desk))

    def test_no_note_from_peer_said(self) -> None:
        self.assertIn("no note from laptop yet", self.run_pc(self.desk))

    def test_log_records_changes_not_repeats(self) -> None:
        commit(self.lt, "u.txt", "unpushed")
        self.run_pc(self.lap)
        syncthing(self.lap, self.desk)
        self.run_pc(self.desk)
        self.run_pc(self.desk)
        log = (self.desk.sync_dir / "sync.log").read_text(encoding="utf-8")
        self.assertEqual(log.count("laptop has 1 unpushed commit"), 1)

    def test_selftest_passes(self) -> None:
        self.assertEqual(main(["selftest"]), 0)

    def test_install_copies_tool_and_writes_machine(self) -> None:
        install(self.desk, register=False)
        tool = self.desk.sync_dir / "tool"
        self.assertTrue((tool / "machine_sync" / "runner.py").exists())
        self.assertTrue((tool / "run_sync.py").exists())
        self.assertEqual((self.desk.sync_dir / "machine.txt").read_text().strip(), "desktop")

    def _launcher_pc(self):
        """A desktop whose launcher repo's main holds the real machine_sync package, with the tool installed."""
        import shutil
        from pathlib import Path

        from msync.helpers import clone, make_origin
        from machine_sync.settings import Settings

        origin = make_origin(self.tmp, "launcher")
        seed = self.tmp / "seed" / "launcher"
        shutil.copytree(Path(__file__).resolve().parents[2] / "machine_sync", seed / "machine_sync",
                        ignore=shutil.ignore_patterns("__pycache__"))
        run(seed, "add", ".")
        run(seed, "commit", "-m", "tool")
        run(seed, "push")
        home = self.tmp / "pc"
        clone(origin, home / "Marco" / "launcher")
        cfg = Settings(home=home, machine="desktop", repos=("Marco/launcher",), plain_roots={})
        install(cfg, register=False)
        return cfg, seed

    def test_self_update_installs_tested_main(self) -> None:
        from machine_sync.selfupdate import self_update

        cfg, seed = self._launcher_pc()
        self.assertIsNone(self_update(cfg))  # same as main: nothing to do
        settings_py = seed / "machine_sync" / "settings.py"
        settings_py.write_text(settings_py.read_text() + "\nUPDATED = True\n")
        run(seed, "commit", "-am", "update")
        run(seed, "push")
        run(cfg.repo_path("Marco/launcher"), "fetch")
        self.assertIn("updated", self_update(cfg))
        self.assertIn("UPDATED = True", (cfg.sync_dir / "tool" / "machine_sync" / "settings.py").read_text())

    def test_self_update_keeps_tool_when_selftest_fails(self) -> None:
        from machine_sync.selfupdate import self_update

        cfg, seed = self._launcher_pc()
        (seed / "machine_sync" / "status.py").write_text("this is not python(\n")
        run(seed, "commit", "-am", "broken")
        run(seed, "push")
        run(cfg.repo_path("Marco/launcher"), "fetch")
        self.assertIn("failed its self-test", self_update(cfg))
        self.assertNotIn("not python", (cfg.sync_dir / "tool" / "machine_sync" / "status.py").read_text())

    def test_task_xml_has_all_triggers(self) -> None:
        xml = task_xml(r"C:\Py\pythonw.exe", r"C:\Users\User\MachineSync\tool\run_sync.py", "PC\\User")
        for needle in ("PT5M", "<LogonTrigger>", "SessionUnlock", "Power-Troubleshooter", "IgnoreNew",
                       r"C:\Py\pythonw.exe", "run_sync.py", " run"):
            self.assertIn(needle, xml)
