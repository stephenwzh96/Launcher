"""Git calls and what a repo's checkout looks like right now."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
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


def _uncommitted(repo: Path) -> list[str]:
    raw = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    paths, entries = [], raw.split("\0")
    i = 0
    while i < len(entries):
        entry = entries[i]
        if len(entry) > 3:
            paths.append(entry[3:])
            if entry[0] in "RC":  # a rename/copy is followed by its source path
                i += 1
        i += 1
    return paths


def _operation(repo: Path) -> str | None:
    gitdir = Path(out(repo, "rev-parse", "--absolute-git-dir"))
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
    branch = out(repo, "symbolic-ref", "--short", "-q", "HEAD") or None
    head = out(repo, "rev-parse", "HEAD")
    upstream, gone = None, False
    if branch:
        info = out(repo, "for-each-ref", "--format=%(upstream:short)%09%(upstream:track)", f"refs/heads/{branch}")
        name, _, track = info.partition("\t")
        upstream = name or None
        gone = track.strip() == "[gone]"
    upstream_head = out(repo, "rev-parse", "--verify", "-q", f"refs/remotes/{upstream}") if upstream and not gone else ""
    if gone:
        unpushed = 0
    elif upstream:
        unpushed = int(out(repo, "rev-list", "--count", f"{upstream}..HEAD") or 0)
    else:
        unpushed = int(out(repo, "rev-list", "--count", "HEAD", "--not", "--remotes") or 0)
    changed = _uncommitted(repo)
    activity = _reflog_activity(repo)
    for rel in changed:
        try:
            activity = max(activity, (repo / rel).stat().st_mtime)
        except OSError:
            pass  # deleted files have no time; the reflog stands
    return RepoState(branch=branch, head=head, upstream=upstream, upstream_gone=gone,
                     upstream_head=upstream_head or None, unpushed=unpushed, uncommitted=len(changed),
                     operation=_operation(repo), last_activity=activity)
