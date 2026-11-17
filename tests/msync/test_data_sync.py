import os
import time
from pathlib import Path

from machine_sync.data_files import data_files
from machine_sync.data_sync import load_state, read_alive, read_note, sync_data
from msync.helpers import TempDirCase, run, syncthing, two_pcs

SQLITE = b"SQLite format 3\x00" + b"\x00" * 84


class DataSyncTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.desk, self.lap = two_pcs(self.tmp, ("Trend",))
        self.clock = time.time() + 1000  # every real file is "stable" (older than 60 s) at these times
        if self._testMethodName not in ("test_nothing_sent_before_other_pcs_note", "test_bootstrap_keeps_newer_mtime"):
            self.handshake()

    def handshake(self) -> None:
        """Both PCs run once, so each has the other's note (as after the first runs on real PCs)."""
        self.pc_run(self.desk)
        self.exchange()
        self.pc_run(self.lap)
        self.exchange()

    # ---- helpers
    def tick(self) -> float:
        self.clock += 61  # runs are minutes apart on the real PCs
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

    def test_nothing_sent_before_other_pcs_note(self) -> None:
        self.write(self.lap, "data/a.csv", "1")
        self.pc_run(self.lap)  # no note from the desktop yet: it may already have every file
        self.assertEqual(self.outbox_files(self.lap), [])

    def test_note_rewritten_only_when_it_changes(self) -> None:
        note = self.lap.note_path("laptop")
        before = note.stat().st_mtime_ns
        self.pc_run(self.lap)  # nothing changed: only the small "alive" file is rewritten
        self.assertEqual(note.stat().st_mtime_ns, before)
        self.assertLess(read_alive(self.desk, "laptop"), self.clock)  # the desktop still has the handshake's
        self.exchange()
        self.assertEqual(read_alive(self.desk, "laptop"), self.clock)
        self.write(self.lap, "data/a.csv", "1")
        self.pc_run(self.lap)
        self.assertGreater(note.stat().st_mtime_ns, before)

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
        self.pc_run(self.lap)  # missing once: could be a file being regenerated
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
        self.pc_run(self.desk)  # now it knows the laptop lacks its copy: sends it
        self.exchange()
        self.pc_run(self.lap)
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
        self.write(self.lap, "data/busy.csv", "half", age=-30)  # modified 31 s before the next run
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

    # ---- review fixes (final review of 17 Nov)
    def test_clash_detected_when_winner_changed_twice(self) -> None:
        self.synced("data/f.csv", "v1")
        self.write(self.desk, "data/f.csv", "D")
        self.pc_run(self.desk)  # the desktop's edit is recorded, then it sleeps before Syncthing sends it
        self.write(self.lap, "data/f.csv", "L1")
        self.pc_run(self.lap)
        self.write(self.lap, "data/f.csv", "L2!")
        self.pc_run(self.lap)
        self.exchange()
        res = self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/f.csv"), "L2!")
        self.assertTrue(any("data/f.csv" in c for c in res.clashes), res.clashes)
        self.assertEqual([b.read_text() for b in (self.desk.sync_dir / "backup").rglob("f.csv")], ["D"])

    def test_no_false_clash_when_peer_edits_again_before_seeing_take(self) -> None:
        self.synced("data/f.csv", "v1")
        self.write(self.lap, "data/f.csv", "L1")
        self.cycle(self.lap, self.desk)  # the desktop takes L1
        self.write(self.lap, "data/f.csv", "L2!")
        self.pc_run(self.lap)  # before it has seen the desktop's note
        self.exchange()
        res = self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/f.csv"), "L2!")
        self.assertEqual(res.clashes, [])

    def test_file_written_after_scan_is_not_replaced(self) -> None:
        from machine_sync.data_sync import import_from_peer, scan

        self.synced("data/f.csv", "v1")
        self.write(self.lap, "data/f.csv", "L")
        self.write(self.lap, "data/new.csv", "lap new")
        self.pc_run(self.lap)
        self.exchange()
        state = load_state(self.desk)
        now = self.tick()
        scan(self.desk, state, now)
        self.write(self.desk, "data/f.csv", "written after the scan", age=300)
        self.write(self.desk, "data/new.csv", "made here after the scan", age=300)
        res = import_from_peer(self.desk, state, read_note(self.desk, "laptop"), set(), False, now)
        self.assertEqual(self.read(self.desk, "data/f.csv"), "written after the scan")
        self.assertEqual(self.read(self.desk, "data/new.csv"), "made here after the scan")
        self.assertEqual(res.taken, 0)

    def test_locked_clash_target_leaves_no_backup_copies(self) -> None:
        from msync.helpers import locked

        self.synced("data/f.csv", "v1")
        self.write(self.desk, "data/f.csv", "D")
        self.pc_run(self.desk)
        self.write(self.lap, "data/f.csv", "L")
        self.pc_run(self.lap)
        self.exchange()
        with locked(self.path(self.desk, "data/f.csv"), share_read=True):
            for _ in range(3):
                self.pc_run(self.desk)
        self.assertEqual(list((self.desk.sync_dir / "backup").rglob("f.csv*")), [])
        self.assertEqual(list(self.path(self.desk, "data").glob("*.msync-tmp")), [])
        self.pc_run(self.desk)
        self.assertEqual(self.read(self.desk, "data/f.csv"), "L")
        self.assertEqual([b.read_text() for b in (self.desk.sync_dir / "backup").rglob("f.csv")], ["D"])

    def test_no_note_keeps_outbox(self) -> None:
        self.write(self.lap, "data/big.csv", "big")
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), ["Trend/data/big.csv"])
        self.lap.note_path("desktop").unlink()  # the desktop's note unreadable for a moment
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), ["Trend/data/big.csv"])

    def test_unreadable_file_does_not_stop_run(self) -> None:
        from msync.helpers import locked

        self.write(self.lap, "data/a.csv", "a")
        self.write(self.lap, "data/b.csv", "b")
        with locked(self.path(self.lap, "data/a.csv")):
            self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), ["Trend/data/b.csv"])
        self.pc_run(self.lap)
        self.assertEqual(self.outbox_files(self.lap), ["Trend/data/a.csv", "Trend/data/b.csv"])

    def test_note_paths_outside_data_are_refused(self) -> None:
        import json

        from machine_sync.data_files import hash_file

        note = read_note(self.desk, "laptop")
        for rel in ("../evil.txt", "Unknown/x.txt", "Trend/../../evil2.txt"):
            staged = self.desk.peer_outbox / rel
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_text("payload")
            note["files"][rel] = [hash_file(staged), self.clock + 999, "laptop", {"laptop": self.clock + 999}, False]
        self.desk.note_path("laptop").write_text(json.dumps(note))
        self.pc_run(self.desk)
        self.assertFalse((self.desk.home.parent / "evil.txt").exists())
        self.assertFalse((self.desk.home / "Unknown").exists())
        self.assertFalse((self.tmp / "evil2.txt").exists())

    def test_regenerated_file_is_not_a_deletion(self) -> None:
        self.synced("data/panel.csv", "p")
        self.path(self.lap, "data/panel.csv").unlink()  # a job rewriting its output folder
        self.pc_run(self.lap)
        self.exchange()
        self.pc_run(self.desk)
        self.assertTrue(self.path(self.desk, "data/panel.csv").exists())  # one missed run is not a deletion
        self.write(self.lap, "data/panel.csv", "p")
        self.cycle(self.lap, self.desk)
        self.assertEqual(self.read(self.desk, "data/panel.csv"), "p")
        self.assertFalse((self.desk.sync_dir / "backup").exists())

    def test_no_deletions_recorded_while_daily_task_runs(self) -> None:
        self.synced("data/out.csv", "o")
        self.path(self.lap, "data/out.csv").unlink()
        self.pc_run(self.lap, frozen={"Trend"})
        self.pc_run(self.lap, frozen={"Trend"})
        self.exchange()
        self.pc_run(self.desk)
        self.assertTrue(self.path(self.desk, "data/out.csv").exists())

    def test_excluded_files(self) -> None:
        for rel in ("data/ok.csv", "data/pg/PG_VERSION", "data/pg/base/1/2", "data/run.lock", "data/.env",
                    "data/node_modules/x.js", "data/logs/a.txt", "data/x.db-wal", "data/a.sync-conflict-1.csv"):
            self.write(self.lap, rel, "x")
        self.assertEqual(sorted(data_files(self.lap)), ["Trend/data/ok.csv"])

    def test_reappearing_path_after_tombstone_is_new_change(self) -> None:
        self.synced("data/r.csv", "old")
        self.path(self.lap, "data/r.csv").unlink()
        self.pc_run(self.lap)
        self.cycle(self.lap, self.desk)
        self.assertFalse(self.path(self.desk, "data/r.csv").exists())
        self.write(self.desk, "data/r.csv", "restored", age=10 ** 6)  # an old copy put back
        self.cycle(self.desk, self.lap)
        self.assertEqual(self.read(self.lap, "data/r.csv"), "restored")
