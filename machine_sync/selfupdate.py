"""The installed tool (MachineSync\\tool) updates itself from the launcher repo's origin/main, never from whatever
branch the launcher checkout is on, and only after the new copy passes its self-test (design, "Pieces")."""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from .gitops import GIT, NO_WINDOW, out
from .settings import Settings

RUN_SYNC = '''"""Entry point of the installed sync tool (Task Scheduler runs: pythonw -I run_sync.py run)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from machine_sync.__main__ import main  # noqa: E402

sys.exit(main())
'''


def _git_bytes(repo: Path, *args: str) -> bytes | None:
    done = subprocess.run([GIT, "-C", str(repo), *args], capture_output=True, creationflags=NO_WINDOW)
    return done.stdout if done.returncode == 0 else None


def _files(root: Path) -> dict[str, bytes]:
    """Files under root, line endings ignored (a checkout has CRLF where Git's copy has LF)."""
    return {p.relative_to(root).as_posix(): p.read_bytes().replace(b"\r\n", b"\n") for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts}


def self_update(cfg: Settings, python: str | None = None) -> str | None:
    """A message when the tool was updated or an update was refused; None when nothing changed."""
    tool = cfg.sync_dir / "tool"
    launcher = cfg.repo_path("Marco/launcher")
    if not (tool / "machine_sync").exists() or not (launcher / ".git").exists():
        return None
    names = [n for n in out(launcher, "ls-tree", "-r", "--name-only", "origin/main", "machine_sync").splitlines()
             if n and "__pycache__" not in n]
    if not names:
        return None
    wanted = {"run_sync.py": RUN_SYNC.encode()}
    for name in names:
        data = _git_bytes(launcher, "show", f"origin/main:{name}")
        if data is None:
            return None
        wanted[name] = data
    if _files(tool) == {k: v.replace(b"\r\n", b"\n") for k, v in wanted.items()}:
        return None
    staged = cfg.sync_dir / "tool.new"
    shutil.rmtree(staged, ignore_errors=True)
    for name, data in wanted.items():
        (staged / name).parent.mkdir(parents=True, exist_ok=True)
        (staged / name).write_bytes(data)
    test = subprocess.run([python or sys.executable, "-I", str(staged / "run_sync.py"), "selftest"],
                          capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
    if test.returncode != 0:
        shutil.rmtree(staged, ignore_errors=True)
        return "the launcher's main has a sync tool that failed its self-test: kept the installed one"
    old = cfg.sync_dir / "tool.old"
    shutil.rmtree(old, ignore_errors=True)
    try:
        tool.replace(old)
        staged.replace(tool)
    except OSError as err:
        if not tool.exists() and old.exists():
            old.replace(tool)
        return f"could not install the sync tool update ({err}); next run tries again"
    shutil.rmtree(old, ignore_errors=True)
    return "sync tool updated from the launcher's main"
