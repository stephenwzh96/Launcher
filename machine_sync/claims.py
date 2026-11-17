"""One daily run per day (design, "One daily run per day"): before a daily task starts, the launcher pushes a claim
to its GitHub repo, `refs/daily-claims/<claim>/<YYYY-MM-DD>` -> a commit with no parent whose message names the PC.
GitHub takes only the first push: a second, unrelated commit is not a fast-forward and is rejected, so two PCs can
never both hold a day. The holder may re-claim (re-runs, the IBKR cycle's second press). Take-over replaces the claim
only if it is still the one this PC saw (force-with-lease), so two take-overs at once still leave one holder.
Every network call has a time limit: a stalled GitHub refuses the start instead of hanging the launcher."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .gitops import NET, NET_TIMEOUT_S, git, out

REF_PREFIX = "refs/daily-claims"
_MESSAGE = re.compile(r"daily claim (\S+) (\d{4}-\d{2}-\d{2}) by (\S+) at (\S+)")
_IDENTITY = ("-c", "user.name=machine-sync", "-c", "user.email=machine-sync@localhost")
_REJECTED = ("[rejected]", "rejected", "non-fast-forward", "fetch first", "already exists", "stale info")


@dataclass
class ClaimResult:
    ok: bool  # this PC holds the day (or, for holder(), the question was answered)
    holder: str | None = None
    at: str | None = None  # ISO local time of the claim
    error: str | None = None  # GitHub could not be asked
    sha: str | None = None  # the claim commit on GitHub (for a take-over's lease)


def ref_name(claim: str, day: str) -> str:
    return f"{REF_PREFIX}/{claim}/{day}"


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "no detail")


def holder(repo: Path, claim: str, day: str, timeout: float = NET_TIMEOUT_S) -> ClaimResult:
    """Who holds `claim` on `day` on GitHub: ok with holder None when nobody does."""
    ref = ref_name(claim, day)
    listed = git(repo, *NET, "ls-remote", "origin", ref, timeout=timeout)
    if listed.returncode != 0:
        return ClaimResult(False, error=_first_line(listed.stderr))
    if not listed.stdout.strip():
        return ClaimResult(True)
    sha = listed.stdout.split()[0]
    fetched = git(repo, *NET, "fetch", "--quiet", "--no-tags", "origin", f"+{ref}:{ref}", timeout=timeout)
    if fetched.returncode != 0:
        return ClaimResult(False, error=_first_line(fetched.stderr))
    m = _MESSAGE.search(out(repo, "log", "-1", "--format=%B", sha))
    if not m:
        return ClaimResult(True, holder="unknown", sha=sha)
    return ClaimResult(True, holder=m.group(3), at=m.group(4), sha=sha)


def claim(repo: Path, claim: str, day: str, machine: str, take_over: bool = False, now: datetime | None = None,
          lease: str | None = None, timeout: float = NET_TIMEOUT_S) -> ClaimResult:
    """Claim `day` for this PC. ok: this PC holds it now. Refused: ok False with the holder. GitHub unreachable or
    too slow: ok False with an error (the caller must not start the task). take_over replaces the current claim only
    if it is still `lease` (the claim this PC saw; read now when not given)."""
    at = (now or datetime.now()).isoformat(timespec="seconds")
    ref = ref_name(claim, day)
    if take_over and lease is None:
        seen = holder(repo, claim, day, timeout)
        if not seen.ok:
            return seen
        lease = seen.sha or ""
    tree = git(repo, "mktree", input="")
    commit = git(repo, *_IDENTITY, "commit-tree", "--no-gpg-sign", tree.stdout.strip(), "-m",
                 f"daily claim {claim} {day} by {machine} at {at}") if tree.returncode == 0 else tree
    if commit.returncode != 0:
        return ClaimResult(False, error=f"could not make the claim ({_first_line(commit.stderr)})")
    sha = commit.stdout.strip()
    how = [f"--force-with-lease={ref}:{lease}"] if take_over else []
    pushed = git(repo, *NET, "push", "--porcelain", *how, "origin", f"{sha}:{ref}", timeout=timeout)
    if pushed.returncode == 0:
        git(repo, "update-ref", ref, sha)
        prune(repo, timeout=timeout)  # from today's date, never the claim's day: a stray day must not delete live ones
        return ClaimResult(True, holder=machine, at=at, sha=sha)
    said = (pushed.stdout + pushed.stderr).lower()
    if pushed.returncode == 124 or not any(word in said for word in _REJECTED):
        return ClaimResult(False, error=_first_line(pushed.stderr or pushed.stdout))
    held = holder(repo, claim, day, timeout)
    if not held.ok:
        return held
    if held.holder == machine:
        return ClaimResult(True, holder=machine, at=held.at, sha=held.sha)
    return ClaimResult(False, holder=held.holder, at=held.at, sha=held.sha)


def prune(repo: Path, keep_days: int = 30, today: date | None = None, timeout: float = NET_TIMEOUT_S) -> None:
    """Delete claims older than keep_days from GitHub (best effort, one push)."""
    cutoff = (today or date.today()) - timedelta(days=keep_days)
    old = []
    for line in out(repo, *NET, "ls-remote", "origin", f"{REF_PREFIX}/*", timeout=timeout).splitlines():
        ref = line.split("\t")[-1]
        try:
            if date.fromisoformat(ref.rsplit("/", 1)[-1]) < cutoff:
                old.append(ref)
        except ValueError:
            continue
    if old:
        git(repo, *NET, "push", "--quiet", "origin", "--delete", *old, timeout=timeout)
