import sys
import time
from pathlib import Path

from machine_sync.code_sync import repo_note, retry_pending_uv, sync_code
from machine_sync.gitops import read_repo
from msync.helpers import TempDirCase, clone, commit, run, two_pcs


class CodeSyncTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.desk_cfg, self.lap_cfg = two_pcs(self.tmp, ("Trend",))
        self.desk = self.desk_cfg.repo_path("Trend")
        self.lap = self.lap_cfg.repo_path("Trend")
        self.origin = self.tmp / "github" / "Trend.git"
        time.sleep(1.1)  # the laptop's moves below are later than both clones

    def lap_note(self) -> dict:
        return repo_note(read_repo(self.lap), running=False)

    def push_feature(self) -> str:
        run(self.lap, "switch", "-c", "feature")
        commit(self.lap, "f.txt", "f")
        return self._push_u("feature")

    def _push_u(self, branch: str) -> str:
        run(self.lap, "push", "-u", "origin", branch)
        return run(self.lap, "rev-parse", "HEAD")

    def sync_desk(self, peer: dict | None, frozen: bool = False):
        return sync_code(self.desk_cfg, "Trend", peer, frozen=frozen, running=False)

    def test_follows_peer_branch_when_idle(self) -> None:
        head = self.push_feature()
        r = self.sync_desk(self.lap_note())
        s = read_repo(self.desk)
        self.assertEqual((s.branch, s.head, s.upstream), ("feature", head, "origin/feature"))
        self.assertTrue(r.moved)

    def test_does_not_follow_older_activity(self) -> None:
        self.push_feature()
        note = self.lap_note()
        time.sleep(1.1)
        run(self.desk, "switch", "-c", "desk-branch")  # the desktop was worked on more recently
        r = self.sync_desk(note)
        self.assertEqual(read_repo(self.desk).branch, "desk-branch")
        self.assertFalse(r.moved)

    def test_stays_when_working_here(self) -> None:
        self.push_feature()
        (self.desk / "README.md").write_text("desk edit\n")
        r = self.sync_desk(self.lap_note())
        self.assertEqual(read_repo(self.desk).branch, "main")
        self.assertFalse(r.moved)
        self.assertIn("edits on this PC", r.line)

    def test_peer_unpushed_goes_to_last_pushed(self) -> None:
        pushed = self.push_feature()
        commit(self.lap, "g.txt", "g")  # not pushed
        r = self.sync_desk(self.lap_note())
        s = read_repo(self.desk)
        self.assertEqual((s.branch, s.head), ("feature", pushed))
        self.assertIn("laptop has 1 unpushed commit", r.line)

    def test_never_moves_local_only_commits(self) -> None:
        run(self.desk, "switch", "-c", "feature")
        commit(self.desk, "mine.txt", "only here")
        run(self.desk, "switch", "main")
        time.sleep(1.1)
        self.push_feature()
        r = self.sync_desk(self.lap_note())
        self.assertEqual(read_repo(self.desk).branch, "main")
        self.assertFalse(r.moved)
        self.assertTrue(any("feature" in w and "GitHub lacks" in w for w in r.warnings), r.warnings)

    def test_fast_forwards_non_checked_out_branches(self) -> None:
        self.push_feature()
        run(self.desk, "fetch")
        run(self.desk, "switch", "feature")
        run(self.desk, "switch", "main")
        newer = commit(self.lap, "g.txt", "g", push=True)
        self.sync_desk(None)
        self.assertEqual(run(self.desk, "rev-parse", "feature"), newer)
        self.assertEqual(read_repo(self.desk).branch, "main")

    def _merge_and_delete_on_github(self, branch: str) -> str:
        cloud = clone(self.origin, self.tmp / "cloud" / "Trend")
        run(cloud, "fetch", "origin", branch)
        run(cloud, "merge", "--no-ff", "-m", "merge", f"origin/{branch}")
        run(cloud, "push", "origin", "main")
        run(cloud, "push", "origin", "--delete", branch)
        return run(cloud, "rev-parse", "HEAD")

    def test_gone_branch_falls_back(self) -> None:
        run(self.lap, "switch", "-c", "claude/x")
        commit(self.lap, "x.txt", "x")
        self._push_u("claude/x")
        merged = self._merge_and_delete_on_github("claude/x")
        desk_note = repo_note(read_repo(self.desk), running=False)
        r = sync_code(self.lap_cfg, "Trend", desk_note, frozen=False, running=False)
        s = read_repo(self.lap)
        self.assertEqual((s.branch, s.head), ("main", merged))
        self.assertTrue(run(self.lap, "rev-parse", "--verify", "claude/x"))  # local branch kept
        self.assertIn("deleted on GitHub", r.line)

    def test_follower_ignores_gone_peer_branch(self) -> None:
        run(self.lap, "switch", "-c", "claude/x")
        commit(self.lap, "x.txt", "x")
        self._push_u("claude/x")
        merged = self._merge_and_delete_on_github("claude/x")
        run(self.lap, "fetch", "--prune")
        self.sync_desk(self.lap_note())
        s = read_repo(self.desk)
        self.assertEqual((s.branch, s.head), ("main", merged))

    def test_frozen_does_not_move(self) -> None:
        self.push_feature()
        r = self.sync_desk(self.lap_note(), frozen=True)
        self.assertEqual(read_repo(self.desk).branch, "main")
        self.assertFalse(r.moved)
        self.assertIn("kept for today's daily run", r.line)

    def test_split_branch_flagged(self) -> None:
        commit(self.lap, "l.txt", "laptop", push=True)
        commit(self.desk, "d.txt", "desktop")  # not pushed: main has split
        r = self.sync_desk(None)
        self.assertFalse(r.moved)
        self.assertTrue(any("merge by hand" in w for w in r.warnings), r.warnings)

    def test_ignored_files_survive_checkout(self) -> None:
        (self.desk / "data").mkdir()
        (self.desk / "data" / "keep.csv").write_text("desk data")
        (self.desk / "run.log").write_text("desk log")  # ignored here, tracked on the laptop's branch
        run(self.lap, "switch", "-c", "feature")
        (self.lap / "run.log").write_text("tracked log")
        run(self.lap, "add", "-f", "run.log")
        run(self.lap, "commit", "-m", "track run.log")
        self._push_u("feature")
        r = self.sync_desk(self.lap_note())
        self.assertEqual((self.desk / "run.log").read_text(), "desk log")
        self.assertEqual((self.desk / "data" / "keep.csv").read_text(), "desk data")
        self.assertFalse(r.moved)
        self.assertTrue(r.warnings)

    def test_after_move_reports_npm_and_lock(self) -> None:
        (self.lap / "dashboard").mkdir()
        (self.lap / "dashboard" / "package-lock.json").write_text("{}")
        (self.lap / "requirements.lock.txt").write_text("pyyaml==6.0.2\n")
        run(self.lap, "add", ".")
        run(self.lap, "commit", "-m", "deps")
        run(self.lap, "push")
        r = self.sync_desk(None)
        self.assertTrue(r.moved)
        self.assertTrue(any("npm ci" in w and "dashboard" in w for w in r.warnings), r.warnings)
        self.assertTrue(any("requirements.lock.txt" in w for w in r.warnings), r.warnings)

    def _fake_uv(self) -> tuple[list[str], Path]:
        log = self.tmp / "uv_calls.txt"
        script = self.tmp / "fake_uv.py"
        script.write_text(f"import sys, os\nopen({str(log)!r}, 'a').write(os.getcwd() + ' ' + ' '.join(sys.argv[1:]) + '\\n')\n")
        return [sys.executable, str(script)], log

    def _push_lock_change(self) -> None:
        (self.lap / "requirements.lock.txt").write_text("pyyaml==6.0.2\n")
        run(self.lap, "add", ".")
        run(self.lap, "commit", "-m", "deps")
        run(self.lap, "push")

    def test_lock_change_runs_uv_sync(self) -> None:
        venv_py = self.desk / ".venv" / "Scripts" / "python.exe"
        venv_py.parent.mkdir(parents=True)
        venv_py.write_text("")
        uv, log = self._fake_uv()
        self._push_lock_change()
        sync_code(self.desk_cfg, "Trend", None, frozen=False, running=False, uv_cmd=uv)
        self.assertIn("pip sync --python", log.read_text())

    def test_lock_change_waits_while_venv_in_use(self) -> None:
        venv_py = self.desk / ".venv" / "Scripts" / "python.exe"
        venv_py.parent.mkdir(parents=True)
        venv_py.write_text("")
        uv, log = self._fake_uv()
        self._push_lock_change()
        r = sync_code(self.desk_cfg, "Trend", None, frozen=False, running=False,
                      in_use={(self.desk / ".venv").resolve()}, uv_cmd=uv)
        self.assertFalse(log.exists())
        self.assertTrue(any("close" in w for w in r.warnings), r.warnings)
        retry_pending_uv(self.desk_cfg, in_use=set(), uv_cmd=uv)
        self.assertIn("pip sync", log.read_text())
