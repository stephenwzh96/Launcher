"""Two PCs whose clocks disagree (the review of 18 Nov: the laptop 10 minutes ahead). Which version of a file is
newer follows the versions' history (version vectors), so the PC whose clock is ahead cannot undo a later change
made from its own; only changes made on both PCs independently fall back to the later stamp."""
import os
import time
from pathlib import Path

from machine_sync.data_sync import clock_skew, load_state, read_alive, read_note, sync_data
from msync.helpers import TempDirCase, syncthing, two_pcs

AHEAD_S = 600  # the laptop's clock is 10 minutes ahead of the desktop's


class SkewedClocksTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.desk, self.lap = two_pcs(self.tmp, ("Trend",))
        self.real = time.time() + 1000  # the true time; every real file is older than 60 s at these times
        self.handshake()

    # ---- helpers: each PC stamps with its own clock
    def clock(self, cfg) -> float:
        return self.real + (AHEAD_S if cfg is self.lap else 0)

    def tick(self) -> None:
        self.real += 61

    def path(self, cfg, rel: str) -> Path:
        return cfg.home / "Trend" / rel

    def write(self, cfg, rel: str, text: str) -> None:
        p = self.path(cfg, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        os.utime(p, (self.real - 120, self.real - 120))  # the file system's time is the true one on both PCs

    def pc_run(self, cfg):
        self.tick()
        return sync_data(cfg, load_state(cfg), read_note(cfg, cfg.peer), self.clock(cfg))

    def exchange(self) -> None:
        syncthing(self.desk, self.lap)
        syncthing(self.lap, self.desk)

    def handshake(self) -> None:
        self.pc_run(self.desk)
        self.exchange()
        self.pc_run(self.lap)
        self.exchange()

    def cycle(self, first, second) -> None:
        self.pc_run(first)
        self.exchange()
        self.pc_run(second)
        self.exchange()

    def synced(self, rel: str, text: str) -> None:
        """A file both PCs have (first seen on the desktop: a first sighting is stamped with the file's own time)."""
        self.write(self.desk, rel, text)
        self.cycle(self.desk, self.lap)
        self.cycle(self.desk, self.lap)
        self.assertEqual(self.path(self.lap, rel).read_text(), text)

    # ---- tests
    def test_later_change_on_slow_clock_pc_wins_on_both(self) -> None:
        """The reviewer's case: the laptop (clock +10 min) changes a file; the desktop takes it, then changes it
        again a few minutes later. Its stamp is earlier than the laptop's, but its version was made from the
        laptop's: it must win on both PCs, with no clash and no backup."""
        self.synced("data/f.csv", "v1")
        self.write(self.lap, "data/f.csv", "laptop")  # a change: stamped with the laptop's clock
        self.cycle(self.lap, self.desk)
        self.assertEqual(self.path(self.desk, "data/f.csv").read_text(), "laptop")
        self.write(self.desk, "data/f.csv", "desktop, later")
        self.cycle(self.desk, self.lap)
        self.cycle(self.desk, self.lap)
        self.assertEqual(self.path(self.lap, "data/f.csv").read_text(), "desktop, later")
        self.assertEqual(self.path(self.desk, "data/f.csv").read_text(), "desktop, later")
        self.assertFalse((self.desk.sync_dir / "backup").exists())
        self.assertFalse((self.lap.sync_dir / "backup").exists())

    def test_later_deletion_on_slow_clock_pc_wins(self) -> None:
        self.synced("data/g.csv", "v1")
        self.write(self.lap, "data/g.csv", "laptop")
        self.cycle(self.lap, self.desk)
        self.assertEqual(self.path(self.desk, "data/g.csv").read_text(), "laptop")
        self.path(self.desk, "data/g.csv").unlink()
        self.pc_run(self.desk)  # missing once
        self.cycle(self.desk, self.lap)
        self.cycle(self.desk, self.lap)
        self.assertFalse(self.path(self.lap, "data/g.csv").exists())
        self.assertFalse(self.path(self.desk, "data/g.csv").exists())

    def test_change_on_both_pcs_still_a_clash_decided_the_same_way_on_both(self) -> None:
        self.synced("data/h.csv", "v1")
        self.write(self.desk, "data/h.csv", "D")
        self.pc_run(self.desk)
        self.write(self.lap, "data/h.csv", "L")
        self.pc_run(self.lap)
        self.exchange()
        for _ in range(2):
            self.cycle(self.desk, self.lap)
        self.assertEqual(self.path(self.desk, "data/h.csv").read_text(),
                         self.path(self.lap, "data/h.csv").read_text())

    def test_own_vector_entry_never_goes_backwards(self) -> None:
        self.write(self.desk, "data/k.csv", "1")
        self.pc_run(self.desk)
        before = load_state(self.desk)["files"]["Trend/data/k.csv"]["vv"]["desktop"]
        self.real -= 3600  # the desktop's clock is set back an hour
        self.write(self.desk, "data/k.csv", "2")
        self.pc_run(self.desk)
        after = load_state(self.desk)["files"]["Trend/data/k.csv"]["vv"]["desktop"]
        self.assertGreater(after, before)

    def test_skew_warning(self) -> None:
        self.write(self.lap, "data/s.csv", "x")
        self.cycle(self.lap, self.desk)
        state, note = load_state(self.desk), read_note(self.desk, "laptop")
        said = clock_skew(self.desk, state, note, read_alive(self.desk, "laptop"), self.clock(self.desk))
        self.assertRegex(said, r"laptop's clock is about (9|10) min ahead")
        self.assertIsNone(clock_skew(self.lap, load_state(self.lap), read_note(self.lap, "desktop"),
                                     read_alive(self.lap, "desktop"), self.clock(self.lap)))
        self.assertIsNone(clock_skew(self.desk, state, note, None, self.clock(self.desk) + AHEAD_S))

    def test_skew_warning_from_heartbeat_alone(self) -> None:
        now = time.time()
        state = {"files": {}}
        self.assertIsNone(clock_skew(self.desk, state, {"written": now + 25, "files": {}}, None, now))
        self.assertIn("about 45 s ahead", clock_skew(self.desk, state, {"written": now, "files": {}}, now + 45, now))
