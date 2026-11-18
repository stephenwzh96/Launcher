"""What the launcher checks before a daily task (tasks.yaml `claim`) starts, beyond the claim itself (review of 18 Nov
2026): the repos the task uses are in step with GitHub (H1). A PC in a temp folder, with a "GitHub" bare repo: no
real path, no network. Run from the launcher folder: .venv\\Scripts\\python.exe -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

from config import TaskConfig
from machine_sync.claims import ClaimResult
from msync.helpers import TempDirCase, clone, commit, make_origin, run
from task_runner import TaskRunner


class Claimer:
    def __init__(self, result: ClaimResult) -> None:
        self.result, self.calls = result, []

    def __call__(self, task, day, machine, take_over, heads=None):
        self.calls.append({"take_over": take_over, "heads": heads})
        return self.result


class StartCheckCase(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.home = self.tmp / "pc"
        self.sync_dir = self.home / "MachineSync"
        self.sync_dir.mkdir(parents=True)
        (self.sync_dir / "machine.txt").write_text("desktop\n")
        self.trend = clone(make_origin(self.tmp, "Trend"), self.home / "Trend")
        self.claimer = Claimer(ClaimResult(True, "desktop", "2026-11-18T09:41:00"))
        self.runners: list[TaskRunner] = []

    def tearDown(self) -> None:
        for r in self.runners:
            for proc in r.procs.values():
                proc.wait(timeout=30)
        super().tearDown()

    def runner(self) -> TaskRunner:
        task = TaskConfig(id="sod", label="MTFA Start of Day", cwd=str(self.trend),
                          cmd=[sys.executable, "-c", "pass"], claim="daily")
        self.runners.append(TaskRunner([task], self.home / "logs", claimer=self.claimer, sync_dir=self.sync_dir,
                                       pruner=lambda: None))
        return self.runners[-1]

    def assert_refused(self, r: TaskRunner, *needles: str, offer: str = "start_anyway", **kw) -> str:
        err = r.start("sod", **kw)
        self.assertIsNotNone(err)
        for needle in needles:
            self.assertIn(needle, err)
        self.assertEqual(r.offers["sod"], offer)
        self.assertNotIn("sod", r.runs)
        self.assertEqual(self.claimer.calls, [])  # refused before the day was claimed
        return err


class InStepTest(StartCheckCase):
    def test_clean_checkout_starts_and_claim_names_its_commit(self) -> None:
        r = self.runner()
        self.assertIsNone(r.start("sod"))
        self.assertEqual(self.claimer.calls[0]["heads"], {"Trend": run(self.trend, "rev-parse", "HEAD")})

    def test_untracked_files_are_fine(self) -> None:
        (self.trend / "scratch.txt").write_text("not in Git")
        self.assertIsNone(self.runner().start("sod"))

    def test_edited_tracked_file_refused_then_started_anyway(self) -> None:
        (self.trend / "README.md").write_text("edited here\n")
        r = self.runner()
        self.assert_refused(r, "Trend: 1 edited tracked file not committed", "start anyway")
        self.assertIsNone(r.start("sod", allow_unsynced=True))
        self.assertTrue(self.claimer.calls[0]["heads"]["Trend"].endswith(" +edits"))

    def test_staged_file_refused(self) -> None:
        (self.trend / "new.py").write_text("x = 1\n")
        run(self.trend, "add", "new.py")
        self.assert_refused(self.runner(), "1 edited tracked file")

    def test_feature_branch_refused(self) -> None:
        run(self.trend, "switch", "-c", "feature")
        self.assert_refused(self.runner(), "Trend: on branch feature, not main")

    def test_unpushed_commit_refused(self) -> None:
        commit(self.trend, "local.txt", "only here")
        self.assert_refused(self.runner(), "Trend: 1 commit not on GitHub")

    def test_split_from_github_refused(self) -> None:
        other = clone(self.tmp / "github" / "Trend.git", self.tmp / "other" / "Trend")
        commit(other, "theirs.txt", "pushed elsewhere", push=True)
        commit(self.trend, "mine.txt", "only here")
        run(self.trend, "fetch")
        self.assert_refused(self.runner(), "split from GitHub's origin/main", "1 commit not on GitHub")

    def test_claim_message_carries_heads_old_readers_still_parse_it(self) -> None:
        from machine_sync.claims import claim, holder

        launcher = clone(make_origin(self.tmp, "launcher"), self.tmp / "desk" / "launcher")
        done = claim(launcher, "daily", "2026-11-18", "desktop", heads={"Trend": "abc123", "IBKR": "def456 +edits"})
        self.assertTrue(done.ok)
        self.assertEqual(holder(launcher, "daily", "2026-11-18").holder, "desktop")
        message = run(launcher, "log", "-1", "--format=%B", done.sha)
        self.assertTrue(message.startswith("daily claim daily 2026-11-18 by desktop at "))
        self.assertIn("\n\nIBKR def456 +edits\nTrend abc123", message)


class TakeOverFenceTest(StartCheckCase):
    """A take-over is refused while the other PC's sync says it is on (ran within 15 minutes) or running a daily
    task; a second, stronger confirmation (force_take_over) overrides it (H3)."""

    def setUp(self) -> None:
        super().setUp()
        self.claimer.result = ClaimResult(True, "desktop", "2026-11-18T10:05:00")

    def peer_note(self, minutes_ago: float, **fields) -> None:
        import json
        import time

        state = self.home / "TripSync" / "_state"  # the laptop's outbox, as the desktop sees it
        state.mkdir(parents=True, exist_ok=True)
        (state / "laptop.json").write_text(json.dumps({"format": 1, "machine": "laptop", "files": {},
                                                       "written": time.time() - minutes_ago * 60, **fields}))

    def test_peer_running_a_daily_task_refuses_then_force_takes_over(self) -> None:
        self.peer_note(120, running_tasks=["sod"])  # off for two hours, but it was running when it last synced
        r = self.runner()
        self.assert_refused(r, "the laptop may still be running", "reported a daily task running there "
                            "(MTFA Start of Day)", offer="take_over_anyway", take_over=True)
        self.assertIsNone(r.start("sod", take_over=True, force_take_over=True))
        self.assertTrue(self.claimer.calls[0]["take_over"])

    def test_peer_on_recently_refuses(self) -> None:
        self.peer_note(3, running_tasks=[])
        self.assert_refused(self.runner(), "its sync ran 3 min ago, so it is on", offer="take_over_anyway",
                            take_over=True)

    def test_heartbeat_file_counts(self) -> None:
        import json
        import time

        self.peer_note(240, running_tasks=[])
        (self.home / "TripSync" / "_state" / "laptop.alive.json").write_text(json.dumps({"written": time.time() - 60}))
        self.assert_refused(self.runner(), "so it is on", offer="take_over_anyway", take_over=True)

    def test_older_tools_note_marks_repos_running(self) -> None:
        self.peer_note(120, repos={"Trend": {"running": True}, "IBKR": {"running": False}})
        self.assert_refused(self.runner(), "(Trend)", offer="take_over_anyway", take_over=True)

    def test_peer_off_and_idle_is_taken_over(self) -> None:
        self.peer_note(120, running_tasks=[])
        r = self.runner()
        self.assertIsNone(r.start("sod", take_over=True))
        self.assertTrue(self.claimer.calls[0]["take_over"])

    def test_no_note_from_peer_is_taken_over(self) -> None:
        self.assertIsNone(self.runner().start("sod", take_over=True))

    def test_plain_start_does_not_look_at_the_peer(self) -> None:
        self.peer_note(1, running_tasks=["sod"])
        self.assertIsNone(self.runner().start("sod"))  # the claim decides; the fence is only for a take-over


if __name__ == "__main__":
    unittest.main()
