import os
import time

from machine_sync.runlock import acquire, release
from msync.helpers import TempDirCase


class RunLockTest(TempDirCase):
    def tearDown(self) -> None:
        release(self.tmp)  # this process holds the lock through an open file until it lets go
        super().tearDown()

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


class OsLockTest(TempDirCase):
    """The lock is an OS lock held through an open file (review of 18 Nov, M10): a holder that crashes releases it
    with its process, and the pid stays readable for messages and for older copies of the module."""
    HOLD = ("import sys, time; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
            "from machine_sync.runlock import acquire; print(acquire(Path(sys.argv[2])), flush=True); time.sleep(60)")

    def setUp(self) -> None:
        super().setUp()
        self.procs = []

    def tearDown(self) -> None:
        for proc in self.procs:  # before the folder goes: a live holder keeps the file open
            proc.kill()
            proc.wait(10)
            if proc.stdout:
                proc.stdout.close()
        super().tearDown()

    def spawn(self, *args: str, **kw):
        import subprocess
        import sys

        # the real interpreter, not a venv's python.exe (which runs it as a child: killing that would not end it)
        python = getattr(sys, "_base_executable", None) or sys.executable
        self.procs.append(subprocess.Popen([python, *args], **kw))
        return self.procs[-1]

    def holder(self):
        import subprocess
        from pathlib import Path

        root = str(Path(__file__).resolve().parents[2])
        proc = self.spawn("-I", "-c", self.HOLD, root, str(self.tmp), stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout.readline().strip(), "True")
        return proc

    def test_other_process_holding_it_is_respected_and_its_pid_readable(self) -> None:
        from machine_sync.runlock import holder_pid

        proc = self.holder()
        self.assertFalse(acquire(self.tmp, wait_s=0.3))
        self.assertEqual(holder_pid(self.tmp), proc.pid)  # an older copy reads a live pid: held for it too

    def test_crashed_holder_releases_it_at_once(self) -> None:
        proc = self.holder()
        proc.kill()  # no release(): the process just ends
        proc.wait(10)
        self.assertTrue(acquire(self.tmp))
        release(self.tmp)

    def test_older_copys_lock_is_honoured(self) -> None:
        (self.tmp / "run.lock").write_text(str(os.getpid()))  # an older copy: pid only, no OS lock
        self.assertFalse(acquire(self.tmp, wait_s=0.3))

    def test_reused_pid_is_not_a_holder(self) -> None:
        lock = self.tmp / "run.lock"
        later = self.spawn("-c", "import time; time.sleep(30)")  # a live process started after the pid was written
        lock.write_text(str(later.pid))
        old = time.time() - 120
        os.utime(lock, (old, old))
        self.assertTrue(acquire(self.tmp))
        release(self.tmp)

    def test_released_lock_is_free_to_an_older_copy(self) -> None:
        self.assertTrue(acquire(self.tmp))
        release(self.tmp)
        self.assertFalse((self.tmp / "run.lock").exists())  # an older copy creates it exclusively again

    def test_two_starters_never_both_take_it(self) -> None:
        import subprocess
        from pathlib import Path

        (self.tmp / "run.lock").write_text("999999")  # a dead holder's lock: every starter may take it over
        root, at = str(Path(__file__).resolve().parents[2]), time.time() + 1.5
        race = ("import sys, time; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
                "from machine_sync.runlock import acquire; time.sleep(max(0, float(sys.argv[3]) - time.time())); "
                "print(acquire(Path(sys.argv[2])), flush=True); time.sleep(5)")
        starters = [self.spawn("-I", "-c", race, root, str(self.tmp), str(at), stdout=subprocess.PIPE, text=True)
                    for _ in range(6)]
        said = [p.stdout.readline().strip() for p in starters]
        self.assertEqual(said.count("True"), 1, said)

    def test_lock_from_before_the_last_boot_is_not_held(self) -> None:
        """A pid whose start cannot be read (another user's process) holds only a lock written since boot (item 8)."""
        from unittest import mock

        from machine_sync import runlock

        lock = self.tmp / "run.lock"
        lock.write_text(str(os.getpid()))  # a live pid, and an older copy's file (no OS lock)
        written = time.time() - 600
        os.utime(lock, (written, written))
        with mock.patch.object(runlock, "_created", lambda pid: None):
            with mock.patch.object(runlock, "_boot_time", lambda: written - 60):  # written after the boot: held
                self.assertFalse(acquire(self.tmp, wait_s=0.2))
            with mock.patch.object(runlock, "_boot_time", lambda: written + 60):  # before it: a dead PC's lock
                self.assertTrue(acquire(self.tmp))
        release(self.tmp)

    def test_boot_time_is_in_the_past(self) -> None:
        from machine_sync.runlock import _boot_time

        boot = _boot_time()
        self.assertTrue(boot is None or boot < time.time())
