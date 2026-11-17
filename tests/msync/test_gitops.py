import time

from machine_sync.gitops import git, read_repo
from msync.helpers import TempDirCase, clone, commit, make_origin, run


class ReadRepoTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.origin = make_origin(self.tmp)
        self.repo = clone(self.origin, self.tmp / "pc" / "repo")

    def test_read_repo_clean_main(self) -> None:
        s = read_repo(self.repo)
        self.assertEqual(s.branch, "main")
        self.assertEqual(s.head, run(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(s.upstream, "origin/main")
        self.assertFalse(s.upstream_gone)
        self.assertEqual(s.upstream_head, s.head)
        self.assertEqual(s.unpushed, 0)
        self.assertEqual(s.uncommitted, 0)
        self.assertIsNone(s.operation)

    def test_unpushed_and_uncommitted_counted(self) -> None:
        commit(self.repo, "a.txt", "a")
        (self.repo / "README.md").write_text("changed\n")
        (self.repo / "new.txt").write_text("x")
        (self.repo / "data").mkdir()
        (self.repo / "data" / "x.csv").write_text("1")  # ignored: not counted
        s = read_repo(self.repo)
        self.assertEqual(s.unpushed, 1)
        self.assertEqual(s.uncommitted, 1)  # tracked edits only
        self.assertEqual(s.untracked, 1)

    def test_untracked_file_is_not_activity(self) -> None:
        before = read_repo(self.repo).last_activity
        time.sleep(1.1)
        (self.repo / "tws_layouts").mkdir()
        (self.repo / "tws_layouts" / "layout.xml").write_text("<x/>")  # an app's untracked file, not code work
        self.assertEqual(read_repo(self.repo).last_activity, before)

    def test_unpushed_without_upstream_counts_commits_github_lacks(self) -> None:
        run(self.repo, "switch", "-c", "local-only")
        commit(self.repo, "a.txt", "a")
        s = read_repo(self.repo)
        self.assertIsNone(s.upstream)
        self.assertEqual(s.unpushed, 1)

    def test_gone_upstream(self) -> None:
        run(self.repo, "switch", "-c", "feature")
        commit(self.repo, "f.txt", "f")
        run(self.repo, "push", "-u", "origin", "feature")
        other = clone(self.origin, self.tmp / "other" / "repo")
        run(other, "push", "origin", "--delete", "feature")
        run(self.repo, "fetch", "--prune")
        s = read_repo(self.repo)
        self.assertEqual(s.branch, "feature")
        self.assertTrue(s.upstream_gone)
        self.assertEqual(s.unpushed, 0)

    def test_operation_in_progress(self) -> None:
        run(self.repo, "switch", "-c", "side")
        commit(self.repo, "README.md", "side\n")
        run(self.repo, "switch", "main")
        commit(self.repo, "README.md", "main\n")
        try:
            run(self.repo, "merge", "side")
        except AssertionError:
            pass  # conflict expected
        self.assertEqual(read_repo(self.repo).operation, "merge")

    def test_last_activity_ignores_tool_moves(self) -> None:
        before = read_repo(self.repo).last_activity
        other = clone(self.origin, self.tmp / "other" / "repo")
        commit(other, "b.txt", "b", push=True)
        time.sleep(1.1)
        git(self.repo, "fetch", check=True)
        git(self.repo, "merge", "--ff-only", "@{u}", check=True)
        self.assertEqual(read_repo(self.repo).last_activity, before)
        time.sleep(1.1)
        commit(self.repo, "c.txt", "c")
        self.assertGreater(read_repo(self.repo).last_activity, before)

    def test_uncommitted_edit_counts_as_activity(self) -> None:
        before = read_repo(self.repo).last_activity
        time.sleep(1.1)
        (self.repo / "README.md").write_text("edited\n")
        self.assertGreater(read_repo(self.repo).last_activity, before)
