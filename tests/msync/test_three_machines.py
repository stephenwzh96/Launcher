"""Three machines (design of 20 Nov 2026): the desktop, the laptop and the VPS, each with its own outbox shared with
the other two. A change reaches both others from its maker's outbox only; Syncthing passes an outbox on through a PC
holding a copy; the versions of a PC quiet for RELAY_AFTER_H are sent by the others; a PC that never wrote a note is
not waited for; a deletion stays in the notes until every PC shows it; a PC whose note cannot be read keeps what is
on its way; the code follows the PC last worked on, of all of them."""
import os
import shutil
import time
import unittest
from datetime import datetime, timedelta

from machine_sync.data_sync import ImportResult, load_state, read_note, read_peer_notes, sync_data
from machine_sync.gitops import read_repo
from machine_sync.runner import leading_peer, run_once
from machine_sync.settings import FORGET_AFTER_DAYS, RELAY_AFTER_H, TOMBSTONE_DAYS
from machine_sync.status import render
from msync.helpers import TempDirCase, commit, plain_pcs, relay, run, syncthing, three_pcs


class ThreeMachineDataTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.pcs = plain_pcs(self.tmp)
        self.desk, self.lap, self.vps = self.pcs["desktop"], self.pcs["laptop"], self.pcs["vps"]
        self.clock = time.time() + 1000  # every real file is "stable" (older than 60 s) at these times
        if not self._testMethodName.startswith("test_join"):
            self.round()
            self.round()  # every PC has run and every PC has seen the others' notes

    # ---- helpers
    def tick(self) -> float:
        self.clock += 61
        return self.clock

    def path(self, cfg, rel: str):
        return cfg.home / "Data" / rel

    def write(self, cfg, rel: str, text: str, age: float = 600):
        p = self.path(cfg, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        os.utime(p, (self.clock - age, self.clock - age))
        return p

    def read(self, cfg, rel: str) -> str:
        return self.path(cfg, rel).read_text()

    def run_pc(self, cfg) -> ImportResult:
        return sync_data(cfg, load_state(cfg), read_peer_notes(cfg), self.tick())

    def step(self, cfg, to=None) -> ImportResult:
        """One sync run on cfg, then Syncthing sends its outbox to `to` (default: both others)."""
        res = self.run_pc(cfg)
        for other in (to if to is not None else [p for p in self.pcs.values() if p is not cfg]):
            syncthing(cfg, other)
        return res

    def round(self, pcs=None) -> None:
        for cfg in (pcs or list(self.pcs.values())):
            self.step(cfg, to=[p for p in (pcs or self.pcs.values()) if p is not cfg])

    def staged(self, cfg, rel: str) -> bool:
        return (cfg.own_outbox / "Data" / rel).exists()

    def outbox_data(self, cfg) -> list[str]:
        return sorted(p.name for p in (cfg.own_outbox / "Data").glob("*")) if (cfg.own_outbox / "Data").exists() else []

    # ---- a change, and its maker's outbox
    def test_change_reaches_both_others_from_its_makers_outbox_only(self) -> None:
        self.write(self.lap, "a.csv", "L1")
        self.step(self.lap)
        self.assertTrue(self.staged(self.lap, "a.csv"))
        self.step(self.desk)
        self.step(self.vps)
        self.assertEqual(self.read(self.desk, "a.csv"), "L1")
        self.assertEqual(self.read(self.vps, "a.csv"), "L1")
        self.assertFalse(self.staged(self.desk, "a.csv"))  # taken, never staged again: nothing is sent twice
        self.assertFalse(self.staged(self.vps, "a.csv"))
        self.step(self.lap)  # both notes now show it
        self.assertFalse(self.staged(self.lap, "a.csv"))

    def test_vps_passes_the_desktops_outbox_on_to_the_laptop(self) -> None:
        self.write(self.desk, "d.csv", "D1")
        self.step(self.desk, to=[self.vps])  # the laptop is off
        self.step(self.vps, to=[self.desk])
        # the desktop goes off; the laptop comes on, and Syncthing serves it the desktop's outbox from the VPS's copy
        relay(self.vps, "desktop", self.lap)
        syncthing(self.vps, self.lap)
        self.run_pc(self.lap)
        self.assertEqual(self.read(self.lap, "d.csv"), "D1")

    def test_versions_of_a_quiet_pc_are_sent_by_the_others(self) -> None:
        self.write(self.desk, "q.csv", "Q1")
        self.step(self.desk, to=[self.vps])  # the laptop is off; the desktop's outbox never reaches it
        self.step(self.vps, to=[self.desk])
        self.assertFalse(self.staged(self.vps, "q.csv"))  # the desktop is about: it sends its own
        self.clock += RELAY_AFTER_H * 3600 + 60  # the desktop has been off since
        self.step(self.vps, to=[self.lap])
        self.assertTrue(self.staged(self.vps, "q.csv"))
        self.run_pc(self.lap)
        self.assertEqual(self.read(self.lap, "q.csv"), "Q1")
        self.step(self.lap)
        self.round()  # the desktop is back: every PC shows the file
        self.step(self.vps)
        self.assertFalse(self.staged(self.vps, "q.csv"))

    # ---- a PC that has not joined yet, and joining
    def test_join_not_yet_two_pcs_work_as_before(self) -> None:
        two = [self.desk, self.lap]
        self.write(self.lap, "x.csv", "X")
        self.round(two)
        self.round(two)
        self.assertEqual(self.read(self.desk, "x.csv"), "X")
        self.assertEqual(self.outbox_data(self.lap), [])  # the desktop has it; the VPS is not waited for
        text = render(self.desk, datetime.fromtimestamp(self.clock), [], ImportResult(), load_state(self.desk),
                      read_peer_notes(self.desk), [], [], {})
        self.assertIn("laptop last ran", text)
        self.assertIn("vps not in the sync yet", text)

    def test_join_with_a_seed_sends_nothing(self) -> None:
        two = [self.desk, self.lap]
        for i in range(3):
            self.write(self.desk, f"s{i}.csv", f"S{i}")
        self.write(self.lap, "l.csv", "made on the laptop")
        self.round(two)
        self.round(two)
        # the seed: the desktop's data on the VPS with its files' times (tar keeps them, as copy2 does here)
        shutil.copytree(self.desk.home / "Data", self.vps.home / "Data")
        syncthing(self.desk, self.vps)
        syncthing(self.lap, self.vps)
        self.round()
        self.round()
        for cfg in self.pcs.values():
            self.assertEqual(self.outbox_data(cfg), [], cfg.machine)
        self.assertEqual(self.read(self.vps, "l.csv"), "made on the laptop")

    def test_join_missing_a_file_gets_it_from_its_maker(self) -> None:
        two = [self.desk, self.lap]
        self.write(self.desk, "s.csv", "S")
        self.write(self.lap, "only.csv", "laptop's")
        self.round(two)
        self.round(two)
        shutil.copytree(self.desk.home / "Data", self.vps.home / "Data")
        (self.vps.home / "Data" / "only.csv").unlink()  # not in the seed
        syncthing(self.desk, self.vps)
        syncthing(self.lap, self.vps)
        self.step(self.vps)  # its first note: the others learn what it lacks
        self.step(self.desk)
        self.assertFalse(self.staged(self.desk, "only.csv"))  # the laptop made it, and is about: it sends it
        self.step(self.lap)
        self.assertTrue(self.staged(self.lap, "only.csv"))
        self.step(self.vps)
        self.assertEqual(self.read(self.vps, "only.csv"), "laptop's")

    # ---- deletions, clashes, an unreadable note
    def test_deletion_stays_in_the_notes_until_every_pc_shows_it(self) -> None:
        self.write(self.desk, "t.csv", "T")
        self.round()
        self.round()
        self.path(self.desk, "t.csv").unlink()
        self.step(self.desk)
        self.step(self.desk)  # missing on two runs: a deletion
        self.step(self.vps)  # the VPS takes it; the laptop is off
        self.assertFalse(self.path(self.vps, "t.csv").exists())
        self.clock += (TOMBSTONE_DAYS + 1) * 86400
        self.step(self.desk)
        self.assertTrue(read_note(self.desk, "desktop")["files"]["Data/t.csv"][4])  # kept: the laptop has not shown it
        self.step(self.lap)
        self.assertFalse(self.path(self.lap, "t.csv").exists())
        self.step(self.desk)
        self.assertNotIn("Data/t.csv", read_note(self.desk, "desktop")["files"])

    def test_change_on_two_pcs_ends_the_same_on_all_three(self) -> None:
        self.write(self.desk, "c.csv", "v1")
        self.round()
        self.round()
        self.write(self.desk, "c.csv", "D")
        self.step(self.desk, to=[self.vps])
        self.write(self.lap, "c.csv", "L")
        self.step(self.lap, to=[self.vps])
        for _ in range(3):
            self.round()
        self.assertEqual({self.read(cfg, "c.csv") for cfg in self.pcs.values()}, {"L"})  # the later change
        kept_copy = [cfg.machine for cfg in self.pcs.values() if (cfg.sync_dir / "backup").exists()]
        self.assertEqual(kept_copy, ["desktop"])  # only the PC whose own change lost keeps its copy

    def test_a_pc_whose_note_cannot_be_read_keeps_what_is_on_its_way(self) -> None:
        self.write(self.desk, "u.csv", "U")
        self.step(self.desk)
        self.desk.note_path("vps").unlink()  # the VPS's note cannot be read on the desktop (missing, a newer tool)
        self.step(self.lap)
        self.run_pc(self.desk)
        self.assertTrue(self.staged(self.desk, "u.csv"))  # the laptop has it now, but the VPS may not
        syncthing(self.vps, self.desk)
        self.step(self.vps)
        self.run_pc(self.desk)
        self.assertFalse(self.staged(self.desk, "u.csv"))  # every PC shows it

    def test_a_pc_gone_for_30_days_is_no_longer_waited_for(self) -> None:
        self.write(self.desk, "g.csv", "G")
        self.step(self.desk, to=[self.lap])
        self.step(self.lap)
        self.desk.note_path("vps").unlink()  # the VPS was rebuilt: its outbox folder is gone
        self.run_pc(self.desk)
        self.assertTrue(self.staged(self.desk, "g.csv"))  # still waited for
        self.clock += (FORGET_AFTER_DAYS + 1) * 86400
        self.run_pc(self.desk)
        self.assertFalse(self.staged(self.desk, "g.csv"))  # no longer waited for: the laptop has it
        text = render(self.desk, datetime.fromtimestamp(self.clock), [], ImportResult(), load_state(self.desk),
                      read_peer_notes(self.desk), [], [], {})
        self.assertIn("no note from vps for 31 days: no longer waited for", text)

    def test_an_unreadable_but_running_pc_is_not_relayed(self) -> None:
        self.write(self.vps, "v.csv", "V")
        self.step(self.vps, to=[self.desk])
        self.run_pc(self.desk)  # the desktop takes it; the laptop is off
        self.clock += RELAY_AFTER_H * 3600 + 60
        self.step(self.vps, to=[self.desk])  # the VPS runs on (its heartbeat is fresh)...
        self.desk.note_path("vps").unlink()  # ...but its note cannot be read here (a newer tool, say)
        self.run_pc(self.desk)
        self.assertFalse(self.staged(self.desk, "v.csv"))  # not taken for a quiet PC: its own outbox has it


class LeadingPeerTest(unittest.TestCase):
    def test_the_pc_last_worked_on_leads(self) -> None:
        notes = {"laptop": {"repos": {"Trend": {"last_activity": 10, "head": "a"}}},
                 "vps": {"repos": {"Trend": {"last_activity": 20, "head": "b"}}}}
        self.assertEqual(leading_peer(notes, "Trend")[0], "vps")
        self.assertEqual(leading_peer({**notes, "vps": None}, "Trend")[0], "laptop")  # a note not followed
        self.assertEqual(leading_peer(notes, "IBKR"), (None, None))


class ThreeMachineRunnerTest(TempDirCase):
    def test_code_follows_the_pc_last_worked_on(self) -> None:
        desk, lap, vps = three_pcs(self.tmp, ("Trend",))
        pcs = (desk, lap, vps)
        now = datetime.now() + timedelta(minutes=5)

        def sync(cfg) -> str:
            text = run_once(cfg, now=now, procs=[], tasks=[])
            for other in pcs:
                if other is not cfg:
                    syncthing(cfg, other)
            return text

        time.sleep(1.1)
        lt = lap.repo_path("Trend")
        run(lt, "switch", "-c", "feature")
        head = commit(lt, "f.txt", "f")
        run(lt, "push", "-u", "origin", "feature")
        for cfg in pcs:  # first runs: each PC learns what the others have
            sync(cfg)
        texts = {cfg.machine: sync(cfg) for cfg in (desk, vps)}
        for cfg in (desk, vps):
            repo = read_repo(cfg.repo_path("Trend"))
            self.assertEqual((repo.branch, repo.head), ("feature", head), cfg.machine)
            self.assertRegex(texts[cfg.machine], r"same as (laptop|desktop|vps)")
