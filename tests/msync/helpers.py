"""Test helpers for machine_sync: a bare "GitHub" repo per app, two PCs (desktop and laptop) in temp folders, and
Syncthing simulated by mirroring a PC's outbox to the same folder under the other PC's home."""
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from machine_sync.settings import Settings

PLAIN_ENV = {k: v for k, v in os.environ.items() if k != "GIT_REFLOG_ACTION"}


def run(cwd: Path, *args: str) -> str:
    """Plain git, as Stephen would type it (no machine-sync reflog tag)."""
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=PLAIN_ENV)
    if done.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}: {done.stderr}")
    return done.stdout.strip()


def _identity(repo: Path) -> None:
    run(repo, "config", "user.name", "Test")
    run(repo, "config", "user.email", "test@example.invalid")
    run(repo, "config", "core.autocrlf", "false")


def make_origin(tmp: Path, name: str = "repo") -> Path:
    """A bare repo with `main` holding README.md and a .gitignore that ignores data/."""
    bare = tmp / "github" / f"{name}.git"
    bare.mkdir(parents=True)
    run(bare, "init", "--bare", "-b", "main")
    seed = tmp / "seed" / name
    seed.mkdir(parents=True)
    run(seed, "init", "-b", "main")
    _identity(seed)
    (seed / "README.md").write_text("readme\n")
    (seed / ".gitignore").write_text("data/\n*.log\n")
    run(seed, "add", ".")
    run(seed, "commit", "-m", "seed")
    run(seed, "remote", "add", "origin", str(bare))
    run(seed, "push", "-u", "origin", "main")
    return bare


def clone(origin: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(dest.parent, "clone", str(origin), dest.name)
    _identity(dest)
    return dest


def commit(repo: Path, name: str, text: str, push: bool = False) -> str:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    run(repo, "add", name)
    run(repo, "commit", "-m", f"change {name}")
    if push:
        run(repo, "push")
    return run(repo, "rev-parse", "HEAD")


def two_pcs(tmp: Path, repos: tuple[str, ...] = ("Trend",)) -> tuple[Settings, Settings]:
    """Desktop and laptop homes, each with a clone of every repo from shared bare origins."""
    pcs = []
    origins = {r: make_origin(tmp, r.replace("/", "_")) for r in repos}
    for machine in ("desktop", "laptop"):
        home = tmp / machine
        for r in repos:
            clone(origins[r], home / r)
        pcs.append(Settings(home=home, machine=machine, repos=tuple(repos), plain_roots={}))
    return pcs[0], pcs[1]


def syncthing(src: Settings, dst: Settings) -> None:
    """Mirror src's outbox to the same folder under dst's home (what a send-only/receive-only pair does)."""
    source = src.own_outbox
    target = dst.home / source.relative_to(src.home)
    if target.exists():
        shutil.rmtree(target, onexc=_force)
    if source.exists():
        shutil.copytree(source, target)


def _force(func, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE)
    func(path)


class TempDirCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="msync-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, onexc=_force)
