"""One daily run per day (design, "One daily run per day"): before a daily task starts, the launcher pushes a claim
to its GitHub repo, `refs/daily-claims/<claim>/<YYYY-MM-DD>` -> a commit with no parent whose message names the PC.
GitHub takes only the first push: a second, unrelated commit is not a fast-forward and is rejected, so two PCs can
never both hold a day. The holder may re-claim (re-runs, the IBKR cycle's second press); take-over force-pushes."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .gitops import git, out

REF_PREFIX = "refs/daily-claims"
_MESSAGE = re.compile(r"daily claim (\S+) (\d{4}-\d{2}-\d{2}) by (\S+) at (\S+)")
_IDENTITY = ("-c", "user.name=machine-sync", "-c", "user.email=machine-sync@localhost")
_REJECTED = ("[rejected]", "rejected", "non-fast-forward", "fetch first", "already exists")


@dataclass
class ClaimResult:
    ok: bool  # this PC holds the day (or, for holder(), the question was answered)
    holder: str | None = None
    at: str | None = None  # ISO local time of the claim
    error: str | None = None  # GitHub could not be asked


def ref_name(claim: str, day: str) -> str:
    return f"{REF_PREFIX}/{claim}/{day}"


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "no detail")


def holder(repo: Path, claim: str, day: str) -> ClaimResult:
    """Who holds `claim` on `day` on GitHub: ok with holder None when nobody does."""
    ref = ref_name(claim, day)
    listed = git(repo, "ls-remote", "origin", ref)
    if listed.returncode != 0:
        return ClaimResult(False, error=_first_line(listed.stderr))
    if not listed.stdout.strip():
        return ClaimResult(True)
    fetched = git(repo, "fetch", "--quiet", "--no-tags", "origin", f"+{ref}:{ref}")
    if fetched.returncode != 0:
        return ClaimResult(False, error=_first_line(fetched.stderr))
    m = _MESSAGE.search(out(repo, "log", "-1", "--format=%B", ref))
    if not m:
        return ClaimResult(True, holder="unknown")
    return ClaimResult(True, holder=m.group(3), at=m.group(4))


def claim(repo: Path, claim: str, day: str, machine: str, take_over: bool = False,
          now: datetime | None = None) -> ClaimResult:
    """Claim `day` for this PC. ok: this PC holds it now. Refused: ok False with the holder. GitHub unreachable:
    ok False with an error (the caller must not start the task)."""
    at = (now or datetime.now()).isoformat(timespec="seconds")
    tree = git(repo, "mktree", input="")
    commit = git(repo, *_IDENTITY, "commit-tree", tree.stdout.strip(), "-m",
                 f"daily claim {claim} {day} by {machine} at {at}") if tree.returncode == 0 else tree
    if commit.returncode != 0:
        return ClaimResult(False, error=f"could not make the claim ({_first_line(commit.stderr)})")
    ref = ref_name(claim, day)
    pushed = git(repo, "push", "--porcelain", "origin", f"{'+' if take_over else ''}{commit.stdout.strip()}:{ref}")
    if pushed.returncode == 0:
        git(repo, "update-ref", ref, commit.stdout.strip())
        prune(repo, today=date.fromisoformat(day))
        return ClaimResult(True, holder=machine, at=at)
    said = (pushed.stdout + pushed.stderr).lower()
    if not any(word in said for word in _REJECTED):
        return ClaimResult(False, error=_first_line(pushed.stderr or pushed.stdout))
    held = holder(repo, claim, day)
    if not held.ok:
        return held
    if held.holder == machine:
        return ClaimResult(True, holder=machine, at=held.at)
    return ClaimResult(False, holder=held.holder, at=held.at)


def prune(repo: Path, keep_days: int = 30, today: date | None = None) -> None:
    """Delete claims older than keep_days from GitHub (best effort, one push)."""
    cutoff = (today or date.today()) - timedelta(days=keep_days)
    old = []
    for line in out(repo, "ls-remote", "origin", f"{REF_PREFIX}/*").splitlines():
        ref = line.split("\t")[-1]
        try:
            if date.fromisoformat(ref.rsplit("/", 1)[-1]) < cutoff:
                old.append(ref)
        except ValueError:
            continue
    if old:
        git(repo, "push", "--quiet", "origin", "--delete", *old)
