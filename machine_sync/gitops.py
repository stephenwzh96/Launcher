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


NET_TIMEOUT_S = 90  # fetch, push, ls-remote: a stalled connection must not hold a run (or the launcher) for long
NET = ("-c", "http.lowSpeedLimit=1000", "-c", "http.lowSpeedTime=20")  # give up on a transfer stuck below 1 KB/s


def git(repo: Path, *args: str, check: bool = False, input: str | None = None,
        timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run git in repo. GIT_OPTIONAL_LOCKS=0: reading the status never takes index.lock away from Stephen's own
    commands. A call that outlives `timeout` is stopped and returns code 124."""
    env = {**os.environ, "GIT_REFLOG_ACTION": REFLOG_ACTION, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never",
           "GIT_OPTIONAL_LOCKS": "0"}
    cmd = [GIT, "-C", str(repo), *args]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", creationflags=NO_WINDOW, env=env)
    try:
        stdout, stderr = proc.communicate(input, timeout=timeout)
        done = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    except subprocess.TimeoutExpired:
        # git hands the network to a helper (git-remote-https) that keeps the pipes open: end the whole tree,
        # or reading the pipes would wait forever
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, creationflags=NO_WINDOW)
        try:
            proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            pass
        done = subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout:.0f} s")
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {repo}: {done.stderr.strip()[:500]}")
    return done


def out(repo: Path, *args: str, timeout: float | None = None) -> str:
    """Stdout of a git call, stripped; empty when it failed."""
    done = git(repo, *args, timeout=timeout)
    return done.stdout.strip() if done.returncode == 0 else ""


@dataclass
class RepoState:
    branch: str | None  # None when HEAD is detached
    head: str
    upstream: str | None  # "origin/main"
    upstream_gone: bool  # the branch tracked a GitHub branch that no longer exists
    upstream_head: str | None
    unpushed: int  # commits on HEAD that GitHub lacks (0 when the GitHub branch was deleted)
    uncommitted: int  # edited, staged or conflicted tracked files: these stop a branch switch
    untracked: int  # new files Git does not ignore: a switch keeps them, so they never stop one (status only)
    operation: str | None  # "rebase", "merge", "cherry-pick", "bisect" in progress
    last_activity: float  # unix time of Stephen's last move or edit here (the tool's own moves excluded)


def _status(repo: Path) -> dict:
    """One `git status --porcelain=v2 --branch` call: head, branch, upstream, ahead count, changed paths.
    An upstream that is set but missing on the remote has no `branch.ab` line (gone)."""
    raw = git(repo, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all").stdout
    info: dict = {"head": "", "branch": None, "upstream": None, "ahead": None, "changed": [], "untracked": []}
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
            info["untracked"].append(e[2:])
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
        if subject.startswith(REFLOG_ACTION) or subject.startswith("clone:"):
            continue  # this tool's own moves, and a clone (a new PC's checkout is not work there)
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
                     untracked=len(st["untracked"]), operation=_operation(repo), last_activity=activity)
