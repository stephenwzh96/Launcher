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

    def __call__(self, task, day, machine, take_over, record=None):
        self.calls.append({"take_over": take_over, "record": record})
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
        self.assertEqual(self.claimer.calls[0]["record"], [f"Trend {run(self.trend, 'rev-parse', 'HEAD')}"])
        self.assertEqual(r.warnings["sod"], [])

    def test_untracked_files_are_fine(self) -> None:
        (self.trend / "scratch.txt").write_text("not in Git")
        self.assertIsNone(self.runner().start("sod"))

    def test_edited_tracked_files_start_with_a_warning_recorded_in_the_claim(self) -> None:
        """Start of Day rewrites some of Trend's tracked files itself (reports/data_qa.md, trial_log.csv), committed
        hours later: the IBKR cycle's presses and a re-run must still start (review of the branch, item 1)."""
        (self.trend / "README.md").write_text("rewritten by the day's run\n")
        (self.trend / ".gitignore").write_text("data/\n*.log\n*.tmp\n")
        r = self.runner()
        self.assertIsNone(r.start("sod"))
        self.assertEqual(r.warnings["sod"], ["Trend: 2 edited tracked files not committed (recorded in the day's "
                                             "claim)"])
        self.assertEqual(self.claimer.calls[0]["record"][-1], "+edits: Trend 2 files")
        self.assertEqual(r.runs["sod"]["warnings"], r.warnings["sod"])  # kept with the run: the page shows it
        shown = {t["id"]: t for t in r.status()["tasks"]}["sod"]["run"]["warnings"]
        self.assertEqual(shown, r.warnings["sod"])

    def test_staged_file_is_a_warning(self) -> None:
        (self.trend / "new.py").write_text("x = 1\n")
        run(self.trend, "add", "new.py")
        r = self.runner()
        self.assertIsNone(r.start("sod"))
        self.assertIn("Trend: 1 edited tracked file", r.warnings["sod"][0])

    def test_detached_head_refused(self) -> None:
        run(self.trend, "switch", "--detach", "HEAD")
        self.assert_refused(self.runner(), "Trend: not on a branch (detached HEAD)")

    def test_operation_in_progress_refused(self) -> None:
        git_dir = self.trend / ".git"
        (git_dir / "MERGE_HEAD").write_text(run(self.trend, "rev-parse", "HEAD") + "\n")
        self.assert_refused(self.runner(), "Trend: a merge in progress")

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

    def test_a_check_that_fails_to_run_refuses_and_can_be_overridden(self) -> None:
        from unittest import mock

        from machine_sync import startcheck

        r = self.runner()
        with mock.patch.object(startcheck, "code_problems", side_effect=OSError("disk gone")):
            self.assert_refused(r, "could not check this (OSError: disk gone)")
            self.assertIsNone(r.start("sod", allow_unsynced=True))

    def test_code_record_that_fails_says_so_in_the_claim_and_still_starts(self) -> None:
        from unittest import mock

        from machine_sync import startcheck

        r = self.runner()
        with mock.patch.object(startcheck, "code_record", side_effect=OSError("git gone")):
            self.assertIsNone(r.start("sod"))
        self.assertEqual(self.claimer.calls[0]["record"], ["heads unavailable (OSError: git gone)"])
        self.assertEqual(r.runs["sod"]["state"], "running")

    def test_claim_message_carries_heads_old_readers_still_parse_it(self) -> None:
        from machine_sync.claims import claim, holder

        launcher = clone(make_origin(self.tmp, "launcher"), self.tmp / "desk" / "launcher")
        done = claim(launcher, "daily", "2026-11-18", "desktop",
                     record=["IBKR def456", "Trend abc123", "+edits: Trend 2 files"])
        self.assertTrue(done.ok)
        self.assertEqual(holder(launcher, "daily", "2026-11-18").holder, "desktop")
        message = run(launcher, "log", "-1", "--format=%B", done.sha)
        self.assertTrue(message.startswith("daily claim daily 2026-11-18 by desktop at "))
        self.assertIn("\n\nIBKR def456\nTrend abc123\n+edits: Trend 2 files", message)


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


class PendingDataTest(StartCheckCase):
    """The other PC's newer data in the daily tasks' repos, not taken here yet, is a warning with the start (never a
    refusal): up to 5 files, each with why, so the user knows whether waiting helps (M7, review item 2)."""

    def setUp(self) -> None:
        import time

        super().setUp()
        self.now = time.time()

    def note(self, files: dict, fmt: int = 1, seen_min_ago: float = 2) -> None:
        import json

        state = self.home / "TripSync" / "_state"
        state.mkdir(parents=True, exist_ok=True)
        (state / "laptop.json").write_text(json.dumps({"format": fmt, "machine": "laptop", "files": files,
                                                       "written": self.now - seen_min_ago * 60}))

    def state(self, files: dict | None = None, **extra) -> None:
        import json

        (self.sync_dir / "state.json").write_text(json.dumps({"files": files or {}, **extra}))

    def staged(self, rel: str, text: str) -> str:
        from machine_sync.data_files import hash_file

        path = self.home / "TripSync" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return hash_file(path)

    def version(self, h: str | None, min_ago: float, deleted: bool = False) -> list:
        t = self.now - min_ago * 60
        return [h, t, "laptop", {"laptop": t}, deleted]

    def started_with(self) -> list[str]:
        r = self.runner()
        self.assertIsNone(r.start("sod"))  # a warning never refuses
        return r.warnings["sod"]

    def test_arrived_but_not_taken_yet_says_next_sync(self) -> None:
        h = self.staged("Trend/data/x.csv", "new")
        self.note({"Trend/data/x.csv": self.version(h, 3)})
        self.assertEqual(self.started_with(), ["the laptop's newer data is not here yet (1 file): Trend/data/x.csv "
                                               "(changed on the laptop 3 min ago, should arrive with the next sync)"])

    def test_not_arrived_and_peer_quiet_says_when_it_was_last_seen(self) -> None:
        self.note({"Trend/data/x.csv": self.version("abc", 70)}, seen_min_ago=60)
        self.assertIn("Trend/data/x.csv (laptop last seen 60 min ago)", self.started_with()[0])

    def test_held_deletion_says_it_needs_allow_deletes(self) -> None:
        self.state({"Trend/data/old.csv": {"h": "abc", "t": 1.0, "m": "laptop", "vv": {"laptop": 1.0}, "del": False,
                                           "size": 1, "mt": 0}}, held_deletions=["Trend/data/old.csv"])
        self.note({"Trend/data/old.csv": self.version(None, 5, deleted=True)})
        self.assertIn("Trend/data/old.csv (held deletion (needs --allow-deletes))", self.started_with()[0])

    def test_file_in_use_here_says_so(self) -> None:
        self.state(unstable=["Trend/data/x.csv"])
        self.note({"Trend/data/x.csv": self.version("abc", 5)})
        self.assertIn("Trend/data/x.csv (open or in use here)", self.started_with()[0])

    def test_held_while_a_daily_task_runs_here(self) -> None:
        from config import TaskConfig

        self.note({"Trend/data/x.csv": self.version("abc", 5)})
        sod = TaskConfig(id="sod", label="MTFA Start of Day", cwd=str(self.trend), cmd=[sys.executable, "-c", "pass"],
                         claim="daily")
        cycle = TaskConfig(id="cycle", label="IBKR paper cycle", cwd=str(self.trend),
                           cmd=[sys.executable, "-c", "import time; time.sleep(3)"], claim="daily")
        r = TaskRunner([sod, cycle], self.home / "logs", claimer=self.claimer, sync_dir=self.sync_dir,
                       pruner=lambda: None)
        self.runners.append(r)
        self.assertIsNone(r.start("cycle"))
        self.assertIsNone(r.start("sod"))
        self.assertIn("Trend/data/x.csv (held while a daily task runs here)", r.warnings["sod"][0])

    def test_names_five_files_and_counts_the_rest(self) -> None:
        self.note({f"Trend/data/f{i}.csv": self.version(f"h{i}", 2) for i in range(7)})
        said = self.started_with()[0]
        self.assertTrue(said.startswith("the laptop's newer data is not here yet (7 files): Trend/data/f0.csv"), said)
        self.assertEqual(said.count("should arrive with the next sync"), 5)
        self.assertTrue(said.endswith("; and 2 more"), said)

    def test_newer_version_of_a_file_here_is_pending(self) -> None:
        self.state({"Trend/data/x.csv": {"h": "old", "t": 1000.0, "m": "desktop", "vv": {"desktop": 1000.0},
                                         "del": False, "size": 1, "mt": 0}})
        self.note({"Trend/data/x.csv": ["new", self.now, "laptop", {"desktop": 1000.0, "laptop": self.now}, False]})
        self.assertIn("(1 file): Trend/data/x.csv", self.started_with()[0])

    def test_nothing_pending_no_warning(self) -> None:
        self.state({"Trend/data/x.csv": {"h": "abc", "t": 2000.0, "m": "laptop", "vv": {"laptop": 2000.0},
                                         "del": False, "size": 1, "mt": 0}})
        self.note({"Trend/data/x.csv": ["abc", 2000.0, "laptop", {"laptop": 2000.0}, False],  # arrived
                   "Trend/README.md": self.version("tracked", 3),  # tracked by Git here: never taken
                   "Trend/data/gone.csv": self.version(None, 3, deleted=True),  # deleted, and not here
                   "Trend/data/half.csv.tmp": self.version("tmp", 3),  # not data on this PC
                   "FOMC/data/y.csv": self.version("other", 3)})  # a repo no daily task uses
        self.assertEqual(self.started_with(), [])

    def test_this_pcs_newer_version_is_not_pending(self) -> None:
        self.state({"Trend/data/x.csv": {"h": "mine", "t": 500.0, "m": "desktop",
                                         "vv": {"laptop": 2000.0, "desktop": 500.0}, "del": False, "size": 1,
                                         "mt": 0}})
        self.note({"Trend/data/x.csv": ["theirs", 2000.0, "laptop", {"laptop": 2000.0}, False]})  # ours came from it
        self.assertEqual(self.started_with(), [])

    def test_note_from_a_newer_tool_is_not_read(self) -> None:
        self.note({"Trend/data/x.csv": self.version("abc", 2)}, fmt=99)
        self.assertEqual(self.started_with(), [])


class PendingLibrariesTest(StartCheckCase):
    """A daily start waits while the sync could not update the libraries of a repo the task uses (L13)."""

    def pending(self, *apps: Path) -> None:
        import json

        (self.sync_dir / "pending_uv.json").write_text(json.dumps([str(a) for a in apps]))

    def test_pending_libraries_in_the_tasks_repo_refuse_then_start_anyway(self) -> None:
        self.pending(self.trend / "AIJPMT1A_build")
        r = self.runner()
        self.assert_refused(r, "Trend: the libraries of", "were not updated after its last code change")
        self.assertIsNone(r.start("sod", allow_unsynced=True))

    def test_pending_libraries_elsewhere_do_not(self) -> None:
        self.pending(self.home / "Marco" / "FOMC")
        self.assertIsNone(self.runner().start("sod"))


if __name__ == "__main__":
    unittest.main()
