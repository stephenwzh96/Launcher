"""python -m machine_sync run [--allow-deletes] [--update-frozen] | status | selftest | install --machine NAME"""
from __future__ import annotations

import argparse
import importlib
import sys

from .settings import MACHINES, Settings

MODULES = ("settings", "gitops", "code_sync", "data_files", "data_sync", "procs", "daily", "claims", "status",
           "selfupdate", "install", "runlock", "runner")


def selftest() -> int:
    """Every module imports (the self-update runs this on a new copy before installing it)."""
    for name in MODULES:
        importlib.import_module(f"{__package__ or 'machine_sync'}.{name}")
    return 0


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
    if a.cmd == "status":
        _say((cfg.sync_dir / "sync_status.txt").read_text(encoding="utf-8"))
        return 0
    from .runner import run_once

    _say(run_once(cfg, allow_deletes=a.allow_deletes, update_frozen=a.update_frozen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
