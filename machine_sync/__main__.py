"""python -m machine_sync run [--allow-deletes] [--update-frozen] | status | selftest | install --machine NAME"""
from __future__ import annotations

import argparse
import importlib
import sys

from .settings import MACHINES, Settings

MODULES = ("settings", "gitops", "code_sync", "data_files", "data_sync", "procs", "daily", "claims", "status",
           "selfupdate", "install", "runlock", "runner", "startcheck")


def selftest() -> int:
    """Every module imports, and the core decisions give the right answers on made-up data (the self-update runs
    this on a new copy before installing it: an exception refuses the update)."""
    for name in MODULES:
        importlib.import_module(f"{__package__ or 'machine_sync'}.{name}")
    _dry_run()
    return 0


def _dry_run() -> None:
    """Two made-up PCs in a temporary folder (no network, no Git, no real path): a file made on the laptop reaches
    the desktop; then the rules the runs rely on, one example each. Raises when one is wrong."""
    import os
    import shutil
    import tempfile
    import time
    from pathlib import Path

    from .daily import running_tasks
    from .data_files import skipped
    from .data_sync import _newer, load_state, read_note, sync_data
    from .procs import Proc

    with tempfile.TemporaryDirectory(prefix="msync-selftest-") as tmp:
        desk, lap = (Settings(home=Path(tmp) / m, machine=m, repos=(), plain_roots={"Data": []}) for m in MACHINES)
        made = lap.home / "Data" / "a.csv"
        made.parent.mkdir(parents=True)
        made.write_text("1")
        now = time.time() + 1000
        os.utime(made, (now - 600, now - 600))
        for cfg, other in ((desk, lap), (lap, desk), (desk, lap), (lap, desk)):
            now += 61
            sync_data(cfg, load_state(cfg), read_note(cfg, cfg.peer), now)
            mirror = other.home / cfg.own_outbox.name  # Syncthing: this PC's outbox, as the other PC sees it
            shutil.rmtree(mirror, ignore_errors=True)
            shutil.copytree(cfg.own_outbox, mirror)
        arrived = desk.home / "Data" / "a.csv"
        if not arrived.is_file() or arrived.read_text() != "1":
            raise AssertionError("selftest: a new file did not reach the other PC")
    made_from = {"t": 100.0, "m": "laptop", "vv": {"laptop": 100.0}}
    later = {"t": 50.0, "m": "desktop", "vv": {"laptop": 100.0, "desktop": 50.0}}  # made from it, on a slower clock
    if not _newer(later, made_from) or _newer(made_from, later):
        raise AssertionError("selftest: which version is newer")
    if not skipped("Trend/live/.staging/x.json") or skipped("Trend/data/x.csv"):
        raise AssertionError("selftest: what counts as data")
    task = {"id": "sod", "cmd": ["python.exe", "C:/x/tools/daily_cycle.py"]}
    if running_tasks([task], [Proc(1, None, "python tools/daily_cycle.py")]) != {"sod"}:
        raise AssertionError("selftest: a running daily task")


def _say(text: str) -> None:
    if sys.stdout:  # pythonw has no console
        print(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="machine_sync")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="one sync run")
    run.add_argument("--allow-deletes", action="store_true", help="let a large batch of deletions through")
    run.add_argument("--update-frozen", action="store_true", help="update code kept for today's daily run")
    sub.add_parser("status", help="print the last status")
    sub.add_parser("selftest")
    adopt = sub.add_parser("adopt-deletions", help="one-off: delete here (to backup) the shared files the other PC "
                                                   "deleted before this tool existed; dry run without --apply")
    adopt.add_argument("--apply", action="store_true")
    ins = sub.add_parser("install", help="install on this PC and register the task")
    ins.add_argument("--machine", required=True, choices=MACHINES)
    ins.add_argument("--no-register", action="store_true")
    a = p.parse_args(argv)
    if a.cmd == "selftest":
        return selftest()
    if a.cmd == "install":
        from .install import install

        for line in install(Settings.real(a.machine), register=not a.no_register):
            _say(line)
        return 0
    cfg = Settings.real()
    if a.cmd == "adopt-deletions":
        import time
        from collections import Counter

        from . import runlock
        from .data_sync import adopt_peer_deletions, load_state, read_note, trip_baseline

        peer_note = read_note(cfg, cfg.peer)
        if peer_note is None:
            _say(f"no note from the {cfg.peer} yet: nothing to compare")
            return 1
        if not runlock.acquire(cfg.sync_dir, wait_s=120):
            _say("a sync run is in progress; try again in a minute")
            return 1
        try:
            paths = adopt_peer_deletions(cfg, load_state(cfg), peer_note, trip_baseline(cfg), time.time(), a.apply)
        finally:
            runlock.release(cfg.sync_dir)
        for folder, n in Counter("/".join(p.split("/")[:4]) for p in paths).most_common():
            _say(f"{n:5}  {folder}")
        _say(f"{len(paths)} files {'moved to ' + str(cfg.sync_dir / 'backup') if a.apply else 'would be moved (dry run)'}")
        return 0
    if a.cmd == "status":
        _say((cfg.sync_dir / "sync_status.txt").read_text(encoding="utf-8"))
        return 0
    from .runner import run_once

    _say(run_once(cfg, allow_deletes=a.allow_deletes, update_frozen=a.update_frozen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
