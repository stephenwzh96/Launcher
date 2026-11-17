import os
import time
from pathlib import Path

from machine_sync.data_files import data_files
from machine_sync.data_sync import load_state, read_note, sync_data
from msync.helpers import TempDirCase, run, syncthing, two_pcs

SQLITE = b"SQLite format 3\x00" + b"\x00" * 84


class DataSyncTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.desk, self.lap = two_pcs(self.tmp, ("Trend",))
        self.clock = time.time() + 1000  # every real file is "stable" (older than 60 s) at these times

    # ---- helpers
    def tick(self) -> float:
        self.clock += 10
        return self.clock

    def path(self, cfg, rel: str) -> Path:
        return cfg.home / "Trend" / rel

    def write(self, cfg, rel: str, text: str | bytes, age: float = 600) -> Path:
        p = self.path(cfg, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text if isinstance(text, bytes) else text.encode())
        os.utime(p, (self.clock - age, self.clock - age))
        return p

    def read(self, cfg, rel: str) -> str:
        return self.path(cfg, rel).read_text()

    def pc_run(self, cfg, frozen=frozenset(), allow_deletes=False):
        state = load_state(cfg)
        return sync_data(cfg, state, read_note(cfg, cfg.peer), self.tick(), frozen_repos=set(frozen),
                         allow_deletes=allow_deletes)

    def exchange(self) -> None:
        syncthing(self.desk, self.lap)
        syncthing(self.lap, self.desk)

    def cycle(self, first, second) -> None:
        """first runs, Syncthing, second runs, Syncthing."""
        self.pc_run(first)
        self.exchange()
        self.pc_run(second)
        self.exchange()

    def outbox_files(self, cfg) -> list[str]:
        root = cfg.own_outbox
        return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()
                      and not p.relative_to(root).as_posix().startswith("_state"))

    def synced(self, rel: str, text: str) -> None:
        self.write(self.lap, rel, text)
        self.cycle(self.lap, self.desk)
        self.pc_run(self.lap)
        self.exchange()
        self.assertEqual(self.read(self.desk, rel), text)

    # ---- tests
    def test_new_file_reaches_other_pc(self) -> None:
        self.write(self.lap, "data/a.csv", "1")
        self.cycle(self.lap, self.desk)
        self.assertEqual(self.read(self.desk, "data/a.csv"), "1")

    def test_change_reaches_other_pc(self) -> None:
        self.synced("data/a.csv", "1")
        self.write(self.lap, "data/a.csv", "2")
        self.cycle(self.lap, self.desk)
        self.assertEqual(self.read(self.desk, "data/a.csv"), "2")

    def test_change_reaches_other_pc_from_desktop(self) -> None:
        self.synced("data/a.csv", "1")
        self.write(self.desk, "data/a.csv", "from desk")
        self.cycle(self.desk, self.lap)
        self.assertEqual(self.read(self.lap, "data/a.csv"), "from desk")

    def test_no_bounce_back(self) -> None:
        self.synced("data/a.csv", "1")
        self.assertEqual(self.outbox_files(self.desk), [])
        self.assertEqual(self.outbox_files(self.lap), [])  # removed once the desktop's note showed it

    def test_revert_to_earlier_content_propagates(self) -> None:
        self.synced("data/f.csv", "v1")
        self.write(self.desk, "data/f.csv", "v2")
        self.cycle(self.desk, self.lap)
        self.assertEqual(self.read(self.lap, "data/f.csv"), "v2")
        self.write(self.lap, "data/f.csv", "v1", age=10 ** 6)  # put back from an old copy: an old modified time
        self.cycle(self.lap, self.desk)
        self.assertEqual(self.read(self.desk, "data/f.csv"), "v1")
        self.pc_run(self.lap)
        self.assertEqual(self.read(self.lap, "data/f.csv"), "v1")

    def test_clash_backs_up_loser_and_converges(self) -> None:
        self.synced("data/f.csv", "v1")
        self.write(self.desk, "data/f.csv", "D")
        self.pc_run(self.desk)
        self.write(self.lap, "data/f.csv", "L")
        self.pc_run(self.lap)  # later stamp: the laptop's change wins
        self.exchange()
        res = self.pc_run(self.desk)
        self.exchange()
        self.pc_run(self.lap)
        self.assertEqual(self.read(self.desk, "data/f.csv"), "L")
        self.assertEqual(self.read(self.lap, "data/f.csv"), "L")
        self.assertTrue(any("data/f.csv" in c for c in res.clashes), res.clashes)
        backups = list((self.desk.sync_dir / "backup").rglob("f.csv"))
        self.assertEqual([b.read_text() for b in backups], ["D"])
        self.assertTrue(any(c["path"] == "Trend/data/f.csv" for c in read_note(self.lap, "desktop")["clashes"]))

    def test_deletion_propagates_with_backup(self) -> None:
        self.synced("data/gone.csv", "x")
        self.path(self.lap, "data/gone.csv").unlink()
        self.cycle(self.lap, self.desk)
        self.assertFalse(self.path(self.desk, "data/gone.csv").exists())
        self.assertEqual([b.read_text() for b in (self.desk.sync_dir / "backup").rglob("gone.csv")], ["x"])

    def test_deletion_brake_holds_mass_delete(self) -> None:
        for i in range(100):
            self.write(self.lap, f"data/f{i:03}.csv", str(i))
        self.cycle(self.lap, self.desk)
        self.assertEqual(len(list(self.path(self.desk, "data").glob("*.csv"))), 100)
        for i in range(60):
            self.path(self.lap, f"data/f{i:03}.csv").unlink()
        self.pc_run(self.lap)
        self.exchange()
        res = self.pc_run(self.desk)
        self.assertEqual(res.held_deletes, 60)
        self.assertEqual(len(list(self.path(self.desk, "data").glob("*.csv"))), 100)
        res = self.pc_run(self.desk, allow_deletes=True)
        self.assertEqual(res.deleted, 60)
        self.assertEqual(len(list(self.path(self.desk, "data").glob("*.csv"))), 40)

    def test_bootstrap_keeps_newer_mtime(self) -> None:
        self.write(self.desk, "data/b.csv", "desk", age=100)  # the newer copy
        self.write(self.lap, "data/b.csv", "lap", age=1000)
        self.pc_run(self.desk)  # the PC with the newer copy runs first, so run order alone would pick the laptop
        self.exchange()
        self.pc_run(self.lap)
        self.exchange()
        self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/b.csv"), "desk")
        self.assertEqual(self.read(self.lap, "data/b.csv"), "desk")

    def test_waits_for_content(self) -> None:
        self.write(self.lap, "data/late.csv", "late")
        self.pc_run(self.lap)
        self.exchange()
        (self.desk.home / "TripSync" / "Trend" / "data" / "late.csv").unlink()  # the note arrived first
        res = self.pc_run(self.desk)
        self.assertEqual(res.waiting, 1)
        self.assertFalse(self.path(self.desk, "data/late.csv").exists())
        self.exchange()
        self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/late.csv"), "late")

    def test_waits_while_content_differs_from_note(self) -> None:
        self.write(self.lap, "data/late.csv", "complete")
        self.pc_run(self.lap)
        self.exchange()
        (self.desk.home / "TripSync" / "Trend" / "data" / "late.csv").write_text("parti")  # still arriving
        res = self.pc_run(self.desk)
        self.assertEqual(res.waiting, 1)
        self.assertFalse(self.path(self.desk, "data/late.csv").exists())

    def test_tracked_here_not_imported(self) -> None:
        desk_file = self.write(self.desk, "data/tracked.csv", "tracked on desk")
        run(desk_file.parents[1], "add", "-f", "data/tracked.csv")
        run(desk_file.parents[1], "commit", "-m", "track it")
        self.write(self.lap, "data/tracked.csv", "lap data", age=60 * 5)
        self.pc_run(self.lap)
        self.exchange()
        res = self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/tracked.csv"), "tracked on desk")
        self.assertTrue(any("tracked" in s for s in res.skipped), res.skipped)

    def test_frozen_repo_not_imported(self) -> None:
        self.write(self.lap, "data/a.csv", "1")
        self.pc_run(self.lap)
        self.exchange()
        res = self.pc_run(self.desk, frozen={"Trend"})
        self.assertFalse(self.path(self.desk, "data/a.csv").exists())
        self.assertTrue(res.skipped)
        self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/a.csv"), "1")

    def test_unstable_file_not_exported(self) -> None:
        self.write(self.lap, "data/busy.csv", "half", age=0)  # modified 10 s before the next run
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), [])
        self.clock += 100
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), ["Trend/data/busy.csv"])

    def test_sqlite_moves_only_without_wal(self) -> None:
        self.write(self.lap, "data/x.db", SQLITE + b"v1")
        self.write(self.lap, "data/x.db-wal", b"wal")
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), [])
        self.path(self.lap, "data/x.db-wal").unlink()
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), ["Trend/data/x.db"])
        self.exchange()
        self.write(self.desk, "data/x.db-wal", b"open here")
        self.pc_run(self.desk)
        self.assertFalse(self.path(self.desk, "data/x.db").exists())
        self.path(self.desk, "data/x.db-wal").unlink()
        self.pc_run(self.desk)
        self.assertEqual(self.path(self.desk, "data/x.db").read_bytes(), SQLITE + b"v1")

    def test_excluded_files(self) -> None:
        for rel in ("data/ok.csv", "data/pg/PG_VERSION", "data/pg/base/1/2", "data/run.lock", "data/.env",
                    "data/node_modules/x.js", "data/logs/a.txt", "data/x.db-wal", "data/a.sync-conflict-1.csv"):
            self.write(self.lap, rel, "x")
        self.assertEqual(sorted(data_files(self.lap)), ["Trend/data/ok.csv"])

    def test_reappearing_path_after_tombstone_is_new_change(self) -> None:
        self.synced("data/r.csv", "old")
        self.path(self.lap, "data/r.csv").unlink()
        self.cycle(self.lap, self.desk)
        self.assertFalse(self.path(self.desk, "data/r.csv").exists())
        self.write(self.desk, "data/r.csv", "restored", age=10 ** 6)  # an old copy put back
        self.cycle(self.desk, self.lap)
        self.assertEqual(self.read(self.lap, "data/r.csv"), "restored")
