import os
import time

from machine_sync.runlock import acquire, release
from msync.helpers import TempDirCase


class RunLockTest(TempDirCase):
    def test_acquire_and_release(self) -> None:
        self.assertTrue(acquire(self.tmp))
        self.assertFalse(acquire(self.tmp, wait_s=0.2))  # held by this live process
        release(self.tmp)
        self.assertTrue(acquire(self.tmp))

    def test_dead_holder_is_taken_over(self) -> None:
        (self.tmp / "run.lock").write_text("999999")
        self.assertTrue(acquire(self.tmp))

    def test_lock_being_written_counts_as_held(self) -> None:
        (self.tmp / "run.lock").write_text("")  # created, pid not written yet
        self.assertFalse(acquire(self.tmp, wait_s=0.2))

    def test_old_empty_lock_is_stale(self) -> None:
        lock = self.tmp / "run.lock"
        lock.write_text("")
        old = time.time() - 60
        os.utime(lock, (old, old))
        self.assertTrue(acquire(self.tmp))

    def test_release_leaves_another_holders_lock(self) -> None:
        (self.tmp / "run.lock").write_text("999998")
        release(self.tmp)
        self.assertTrue((self.tmp / "run.lock").exists())
