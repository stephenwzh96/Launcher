"""Stop asks a task to end (CTRL_BREAK_EVENT to its process group) before ending it by force. These start real
processes through the venv's python.exe, as the launcher does. Run from the launcher folder:
.venv\\Scripts\\python.exe -m unittest discover tests"""
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from config import TaskConfig
from task_runner import TaskRunner

# A task like Trend's Start of Day: on CTRL_BREAK it records why it ended, then exits 1. "deaf" ignores it.
TASK = """
import signal, sys, time
from pathlib import Path
mark = Path(sys.argv[1])
def on_break(sig, frame):
    mark.write_text("stopped")
    sys.exit(1)
signal.signal(signal.SIGBREAK, signal.SIG_IGN if sys.argv[2] == "deaf" else on_break)
mark.write_text("running")
while True:
    time.sleep(0.1)
"""


class Stop(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = Path(self.dir.name)
        (self.root / "task.py").write_text(TASK)
        self.mark = self.root / "mark.txt"

    def tearDown(self):
        self.dir.cleanup()

    def runner(self, mode: str, grace: float) -> TaskRunner:
        cmd = [sys.executable, str(self.root / "task.py"), str(self.mark), mode]
        return TaskRunner([TaskConfig(id="t", label="T", cwd=str(self.root), cmd=cmd)], self.root / "logs", grace)

    def started(self, runner: TaskRunner) -> None:
        self.assertIsNone(runner.start("t"))
        for _ in range(100):
            if self.mark.exists():
                return
            time.sleep(0.1)
        self.fail("the task did not start")

    def ended(self, runner: TaskRunner, timeout: float = 30) -> dict:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            run = runner.status()["tasks"][0]["run"]
            if run["state"] != "running" and run["stop"]:
                return run
            time.sleep(0.2)
        self.fail("the run did not end")

    def test_asked_and_recorded(self):
        runner = self.runner("normal", grace=20)
        self.started(runner)
        t0 = time.monotonic()
        runner.stop("t")
        self.assertTrue(runner.status()["tasks"][0]["run"]["stopping"])
        run = self.ended(runner)
        self.assertLess(time.monotonic() - t0, 10)  # well before the grace time ran out
        self.assertEqual(self.mark.read_text(), "stopped")  # the task's own handler ran
        self.assertEqual((run["state"], run["stop"], run["exit_code"]), ("stopped", "asked", 1))

    def test_forced_when_it_does_not_end(self):
        runner = self.runner("deaf", grace=2)
        self.started(runner)
        runner.stop("t")
        run = self.ended(runner)
        self.assertEqual(self.mark.read_text(), "running")
        self.assertEqual((run["state"], run["stop"]), ("stopped", "forced"))

    def test_killed_when_it_cannot_be_asked(self):
        runner = self.runner("normal", grace=20)
        self.started(runner)
        with mock.patch("task_runner.send_ctrl_break", return_value=False):
            runner.stop("t")
            run = self.ended(runner)
        self.assertEqual((run["state"], run["stop"]), ("stopped", "killed"))


if __name__ == "__main__":
    unittest.main()
