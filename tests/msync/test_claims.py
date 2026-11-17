from datetime import date

from machine_sync.claims import claim, holder, prune
from msync.helpers import TempDirCase, clone, make_origin, run


class ClaimsTest(TempDirCase):
    def setUp(self) -> None:
        super().setUp()
        self.origin = make_origin(self.tmp, "launcher")
        self.desk = clone(self.origin, self.tmp / "desktop" / "launcher")
        self.lap = clone(self.origin, self.tmp / "laptop" / "launcher")

    def test_holder_none_when_unclaimed(self) -> None:
        r = holder(self.desk, "daily", "2026-11-17")
        self.assertTrue(r.ok)
        self.assertIsNone(r.holder)

    def test_first_claim_wins(self) -> None:
        r = claim(self.desk, "daily", "2026-11-17", "desktop")
        self.assertTrue(r.ok)
        self.assertEqual(r.holder, "desktop")
        self.assertEqual(holder(self.lap, "daily", "2026-11-17").holder, "desktop")

    def test_second_claim_refused(self) -> None:
        claim(self.desk, "daily", "2026-11-17", "desktop")
        r = claim(self.lap, "daily", "2026-11-17", "laptop")
        self.assertFalse(r.ok)
        self.assertEqual(r.holder, "desktop")
        self.assertIsNone(r.error)

    def test_other_days_and_claims_are_separate(self) -> None:
        claim(self.desk, "daily", "2026-11-17", "desktop")
        self.assertTrue(claim(self.lap, "daily", "2026-11-18", "laptop").ok)
        self.assertTrue(claim(self.lap, "other", "2026-11-17", "laptop").ok)

    def test_same_machine_reclaims(self) -> None:
        first = claim(self.desk, "daily", "2026-11-17", "desktop")
        again = claim(self.desk, "daily", "2026-11-17", "desktop")
        self.assertTrue(again.ok)
        self.assertEqual(again.at, first.at)

    def test_take_over_moves_claim(self) -> None:
        claim(self.desk, "daily", "2026-11-17", "desktop")
        r = claim(self.lap, "daily", "2026-11-17", "laptop", take_over=True)
        self.assertTrue(r.ok)
        self.assertEqual(holder(self.desk, "daily", "2026-11-17").holder, "laptop")
        self.assertFalse(claim(self.desk, "daily", "2026-11-17", "desktop").ok)

    def test_unreachable_refuses(self) -> None:
        run(self.lap, "remote", "set-url", "origin", str(self.tmp / "nowhere.git"))
        r = claim(self.lap, "daily", "2026-11-17", "laptop")
        self.assertFalse(r.ok)
        self.assertIsNone(r.holder)
        self.assertTrue(r.error)

    def test_claim_for_another_day_never_prunes_todays(self) -> None:
        today = date.today().isoformat()
        claim(self.desk, "daily", today, "laptop")
        claim(self.desk, "other", "2099-01-01", "desktop")  # a stray far-future day (a wrong clock, a test)
        self.assertEqual(holder(self.lap, "daily", today).holder, "laptop")

    def test_take_over_with_stale_lease_is_refused(self) -> None:
        claim(self.desk, "daily", "2026-11-17", "desktop")
        seen = holder(self.lap, "daily", "2026-11-17").sha
        claim(self.desk, "daily", "2026-11-17", "vps", take_over=True)  # someone else moved it meanwhile
        r = claim(self.lap, "daily", "2026-11-17", "laptop", take_over=True, lease=seen)
        self.assertFalse(r.ok)
        self.assertEqual(r.holder, "vps")
        self.assertEqual(holder(self.desk, "daily", "2026-11-17").holder, "vps")

    def test_claim_ignores_commit_signing_settings(self) -> None:
        run(self.lap, "config", "commit.gpgSign", "true")
        run(self.lap, "config", "gpg.program", "no-such-gpg-program")
        self.assertTrue(claim(self.lap, "daily", "2026-11-17", "laptop").ok)

    def test_claim_times_out_when_github_stalls(self) -> None:
        import socket
        import threading
        import time

        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        threading.Thread(target=lambda: server.accept(), daemon=True).start()
        run(self.lap, "remote", "set-url", "origin", f"http://127.0.0.1:{server.getsockname()[1]}/launcher.git")
        started = time.time()
        r = claim(self.lap, "daily", "2026-11-17", "laptop", timeout=3)
        server.close()
        self.assertFalse(r.ok)
        self.assertTrue(r.error)
        self.assertLess(time.time() - started, 30)

    def test_prune_old_claims(self) -> None:
        claim(self.desk, "daily", "2026-09-01", "desktop")
        claim(self.desk, "daily", "2026-11-17", "desktop")
        prune(self.desk, keep_days=30, today=date(2026, 11, 17))
        refs = run(self.desk, "ls-remote", "origin", "refs/daily-claims/*")
        self.assertIn("2026-11-17", refs)
        self.assertNotIn("2026-09-01", refs)
