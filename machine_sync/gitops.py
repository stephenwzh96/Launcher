"""Git calls and what a repo's checkout looks like right now."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REFLOG_ACTION = "machine-sync"  # the tool's own Git moves carry this, so they never count as Stephen's activity
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def git(repo: Path, *args: str, check: bool = False, input: str | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_REFLOG_ACTION": REFLOG_ACTION, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}
    done = subprocess.run([GIT, "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace", creationflags=NO_WINDOW, env=env, input=input)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {done.stderr.strip()[:500]}")
    return done


def out(repo: Path, *args: str) -> str:
    """Stdout of a git call, stripped; empty when it failed."""
    done = git(repo, *args)
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass
class RepoState:
    branch: str | None  # None when HEAD is detached
    head: str
    upstream: str | None  # "origin/main"
    upstream_gone: bool  # the branch tracked a GitHub branch that no longer exists
    upstream_head: str | None
    unpushed: int  # commits on HEAD that GitHub lacks (0 when the GitHub branch was deleted)
    uncommitted: int  # tracked changes plus untracked files Git does not ignore
    operation: str | None  # "rebase", "merge", "cherry-pick", "bisect" in progress
    last_activity: float  # unix time of Stephen's last move or edit here (the tool's own moves excluded)


def _status(repo: Path) -> dict:
    """One `git status --porcelain=v2 --branch` call: head, branch, upstream, ahead count, changed paths.
    An upstream that is set but missing on the remote has no `branch.ab` line (gone)."""
    raw = git(repo, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all").stdout
    info: dict = {"head": "", "branch": None, "upstream": None, "ahead": None, "changed": []}
    entries = raw.split("\0")
    i = 0
    while i < len(entries):
        e = entries[i]
        if e.startswith("# branch.oid "):
            info["head"] = "" if e[13:] == "(initial)" else e[13:]
        elif e.startswith("# branch.head "):
            info["branch"] = None if e[14:] == "(detached)" else e[14:]
        elif e.startswith("# branch.upstream "):
            info["upstream"] = e[18:]
        elif e.startswith("# branch.ab "):
            info["ahead"] = int(e[12:].split()[0].lstrip("+"))
        elif e.startswith("1 "):
            info["changed"].append(e.split(" ", 8)[-1])
        elif e.startswith("2 "):
            info["changed"].append(e.split(" ", 9)[-1])
            i += 1  # a rename is followed by its original path
        elif e.startswith("u "):
            info["changed"].append(e.split(" ", 10)[-1])
        elif e.startswith("? "):
            info["changed"].append(e[2:])
        i += 1
    return info


@lru_cache(maxsize=64)
def _gitdir(repo: str) -> Path:
    return Path(out(Path(repo), "rev-parse", "--absolute-git-dir"))


def _operation(repo: Path) -> str | None:
    gitdir = _gitdir(str(repo))
    for marker, name in (("rebase-merge", "rebase"), ("rebase-apply", "rebase"), ("MERGE_HEAD", "merge"),
                         ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect")):
        if (gitdir / marker).exists():
            return name
    return None


def _reflog_activity(repo: Path) -> float:
    lines = out(repo, "reflog", "show", "--date=unix", "--format=%gd%x09%gs", "HEAD").splitlines()
    for line in lines:  # newest first
        selector, _, subject = line.partition("\t")
        if subject.startswith(REFLOG_ACTION):
            continue
        try:
            return float(selector[selector.index("{") + 1:selector.index("}")])
        except ValueError:
            continue
    return 0.0


def read_repo(repo: Path) -> RepoState:
    """About three git calls: status (branch, upstream, ahead, changes), the upstream's commit, the reflog."""
    st = _status(repo)
    branch, head, upstream = st["branch"], st["head"], st["upstream"]
    gone = bool(upstream) and st["ahead"] is None
    upstream_head = out(repo, "rev-parse", "--verify", "-q", f"refs/remotes/{upstream}") if upstream and not gone else ""
    if gone:
        unpushed = 0
    elif upstream:
        unpushed = st["ahead"] or 0
    else:
        unpushed = int(out(repo, "rev-list", "--count", "HEAD", "--not", "--remotes") or 0)
    changed = st["changed"]
    activity = _reflog_activity(repo)
    for rel in changed:
        try:
            activity = max(activity, (repo / rel).stat().st_mtime)
        except OSError:
            pass  # deleted files have no time; the reflog stands
    return RepoState(branch=branch, head=head, upstream=upstream, upstream_gone=gone,
                     upstream_head=upstream_head or None, unpushed=unpushed, uncommitted=len(changed),
                     operation=_operation(repo), last_activity=activity)
