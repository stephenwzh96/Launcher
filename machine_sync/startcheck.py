"""Before a daily task starts (the launcher, tasks.yaml `claim`): is this PC in step with GitHub and the other PC?
Every check is local (Git's last fetch, the sync's own files): none needs the network. The launcher refuses the
start when one fails and offers to start anyway (review of 18 Nov 2026, H1); before a take-over it asks whether the
other PC may still be running (H3)."""
from __future__ import annotations

from pathlib import Path

from .code_sync import _is_ancestor, default_branch, pending_uv
from .daily import _repo_of_path, busy_repos
from . import NOTE_FORMAT
from .data_sync import load_state, pending_from_peer, read_alive, read_note
from .gitops import out, read_repo
from .settings import LAUNCHER_REPO, Settings

PEER_RECENT_S = 15 * 60  # the other PC's sync ran this recently: it is on


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _ago(seconds: float) -> str:
    if seconds < 90:
        return "just now"
    if seconds < 90 * 60:
        return f"{seconds / 60:.0f} min ago"
    return f"{seconds / 3600:.1f} h ago"


def task_repos(cfg: Settings, cwd: str, cmd: list[str], launcher: bool = True) -> list[str]:
    """The repos a daily task uses (its folder and command line point into them) and the launcher's own (unless
    launcher=False), those on this PC."""
    repos = busy_repos(cfg, [{"cwd": cwd, "cmd": cmd}]) | ({LAUNCHER_REPO} if launcher else set())
    return sorted(r for r in repos if (cfg.repo_path(r) / ".git").exists())


def repo_problems(path: Path) -> list[str]:
    """Why a repo's checkout is not GitHub's default branch, which refuses a daily start (with the override): off
    that branch, a Git operation in progress, commits not on GitHub, split from it. Edited tracked files are not
    here: Start of Day rewrites some of Trend's itself (reports/data_qa.md, trial_log.csv) and they are committed
    hours later, so they are only a warning (edits()); untracked files are fine."""
    s = read_repo(path)
    found = []
    default = default_branch(path)
    if s.branch is None:
        found.append("not on a branch (detached HEAD)")
    elif default and s.branch != default:
        found.append(f"on branch {s.branch}, not {default}")
    if s.operation:
        found.append(f"a {s.operation} in progress")
    if s.unpushed:
        found.append(f"{_plural(s.unpushed, 'commit')} not on GitHub")
    if s.upstream_head and s.head != s.upstream_head and not _is_ancestor(path, s.head, s.upstream_head) \
            and not _is_ancestor(path, s.upstream_head, s.head):
        found.append(f"split from GitHub's {s.upstream}")
    return found


def edits(cfg: Settings, repos: list[str]) -> dict[str, int]:
    """Edited or staged tracked files per repo (only the repos that have some)."""
    found = {}
    for repo in repos:
        if n := read_repo(cfg.repo_path(repo)).uncommitted:
            found[repo] = n
    return found


def edit_warnings(cfg: Settings, repos: list[str]) -> list[str]:
    """A start goes ahead with edited tracked files; it says so, and the claim records it."""
    return [f"{repo}: {_plural(n, 'edited tracked file')} not committed (recorded in the day's claim)"
            for repo, n in edits(cfg, repos).items()]


def code_problems(cfg: Settings, repos: list[str]) -> list[str]:
    """One line per repo that is not in step, e.g. "Trend: on branch feature, not main; 2 commits not on GitHub"."""
    lines = []
    for repo in repos:
        if found := repo_problems(cfg.repo_path(repo)):
            lines.append(f"{repo}: {'; '.join(found)}")
    return lines


def data_pending(cfg: Settings, repos: set[str]) -> str | None:
    """A line when the other PC's note lists newer versions in `repos` that this PC has not taken yet (M7)."""
    note = read_note(cfg, cfg.peer)
    if not note or note.get("format", 0) > NOTE_FORMAT:
        return None
    waiting = pending_from_peer(cfg, load_state(cfg), note, repos)
    if not waiting:
        return None
    return (f"the {cfg.peer}'s latest changes have not arrived yet ({_plural(len(waiting), 'file')}, e.g. "
            f"{waiting[0]}): wait for the next sync (every 5 minutes)")


def libraries_pending(cfg: Settings, repos: list[str]) -> list[str]:
    """One line per app folder in `repos` whose libraries the sync could not update after a code change (L13)."""
    lines = []
    for app in pending_uv(cfg):
        repo = _repo_of_path(cfg, Path(app))
        if repo in repos:
            lines.append(f"{repo}: the libraries of {app} were not updated after its last code change (uv pip "
                         "sync): see MachineSync\\sync_status.txt; each sync run tries again")
    return lines


def code_record(cfg: Settings, repos: list[str]) -> list[str]:
    """The lines the day's claim records below its first line: "<repo> <HEAD sha>" for each repo, then, when any
    has edited tracked files, "+edits: Trend 2 files, IBKR 1 file"."""
    lines = []
    for repo in repos:
        if sha := out(cfg.repo_path(repo), "rev-parse", "HEAD"):
            lines.append(f"{repo} {sha}")
    if changed := edits(cfg, repos):
        lines.append("+edits: " + ", ".join(f"{repo} {_plural(n, 'file')}" for repo, n in changed.items()))
    return lines


def peer_busy(cfg: Settings, now: float, labels: dict[str, str] | None = None) -> list[str]:
    """Why the other PC may still be running today's daily run, from what its sync last wrote (its note and
    heartbeat): a daily task running there (the note's `running_tasks`; from an older tool, any repo marked
    running), or a sync run within PEER_RECENT_S (it is on). Empty when neither, or it never wrote a note."""
    note = read_note(cfg, cfg.peer) or {}
    try:
        beat = max(float(note.get("written") or 0.0), float(read_alive(cfg, cfg.peer) or 0.0))
    except (TypeError, ValueError):
        beat = 0.0
    if not beat:
        return []
    found = []
    if "running_tasks" in note:
        running = [(labels or {}).get(t, t) for t in note.get("running_tasks") or []]
    else:
        running = sorted(r for r, v in (note.get("repos") or {}).items() if isinstance(v, dict) and v.get("running"))
    if running:
        found.append(f"its last sync ({_ago(now - beat)}) reported a daily task running there "
                     f"({', '.join(running)})")
    if now - beat < PEER_RECENT_S:
        found.append(f"its sync ran {_ago(now - beat)}, so it is on")
    return found
