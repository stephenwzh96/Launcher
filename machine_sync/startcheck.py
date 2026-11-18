"""Before a daily task starts (the launcher, tasks.yaml `claim`): is this PC in step with GitHub and the other PC?
Every check is local (Git's last fetch, the sync's own files): none needs the network. The launcher refuses the
start when one fails and offers to start anyway (review of 18 Nov 2026, H1)."""
from __future__ import annotations

from pathlib import Path

from .code_sync import _is_ancestor, default_branch
from .daily import busy_repos
from .gitops import out, read_repo
from .settings import LAUNCHER_REPO, Settings


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def task_repos(cfg: Settings, cwd: str, cmd: list[str]) -> list[str]:
    """The repos a daily task uses (its folder and command line point into them) and the launcher's own, those on
    this PC."""
    repos = busy_repos(cfg, [{"cwd": cwd, "cmd": cmd}]) | {LAUNCHER_REPO}
    return sorted(r for r in repos if (cfg.repo_path(r) / ".git").exists())


def repo_problems(path: Path) -> list[str]:
    """Why a repo's checkout is not the code GitHub has on its default branch (untracked files are fine)."""
    s = read_repo(path)
    found = []
    default = default_branch(path)
    if s.branch is None:
        found.append("not on a branch (detached HEAD)")
    elif default and s.branch != default:
        found.append(f"on branch {s.branch}, not {default}")
    if s.operation:
        found.append(f"a {s.operation} in progress")
    if s.uncommitted:
        found.append(f"{_plural(s.uncommitted, 'edited tracked file')} not committed")
    if s.unpushed:
        found.append(f"{_plural(s.unpushed, 'commit')} not on GitHub")
    if s.upstream_head and s.head != s.upstream_head and not _is_ancestor(path, s.head, s.upstream_head) \
            and not _is_ancestor(path, s.upstream_head, s.head):
        found.append(f"split from GitHub's {s.upstream}")
    return found


def code_problems(cfg: Settings, repos: list[str]) -> list[str]:
    """One line per repo that is not in step, e.g. "Trend: on branch feature, not main; 2 commits not on GitHub"."""
    lines = []
    for repo in repos:
        if found := repo_problems(cfg.repo_path(repo)):
            lines.append(f"{repo}: {'; '.join(found)}")
    return lines


def heads(cfg: Settings, repos: list[str]) -> dict[str, str]:
    """Each repo's HEAD commit, "+edits" when tracked files differ from it (for the claim's message)."""
    found = {}
    for repo in repos:
        path = cfg.repo_path(repo)
        sha = out(path, "rev-parse", "HEAD")
        if sha:
            found[repo] = sha + (" +edits" if read_repo(path).uncommitted else "")
    return found
