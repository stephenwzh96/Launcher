"""Code step: keep each repo on the branch and commit of the PC last worked on (design, "Code step").
Never commits, pushes, merges, rebases or forces: it only fetches, fast-forwards and switches to commits GitHub has."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path

from .gitops import NET, NET_TIMEOUT_S, NO_WINDOW, RepoState, git, out, read_repo
from .settings import Settings


@dataclass
class RepoResult:
    repo: str
    line: str = ""
    moved: bool = False
    before: str = ""
    after: str = ""
    warnings: list[str] = field(default_factory=list)
    state: RepoState | None = None  # the checkout after this run (for the note)


def repo_note(state: RepoState, running: bool) -> dict:
    """The per-repo part of this PC's note."""
    return {"branch": state.branch, "head": state.head, "upstream": state.upstream,
            "upstream_gone": state.upstream_gone, "upstream_head": state.upstream_head, "unpushed": state.unpushed,
            "uncommitted": state.uncommitted, "untracked": state.untracked, "operation": state.operation,
            "last_activity": state.last_activity, "running": running}


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def _where(branch: str | None, head: str) -> str:
    return f"{branch or 'detached'} @ {head[:7] if head else '-'}"


def _is_ancestor(repo: Path, a: str, b: str) -> bool:
    return git(repo, "merge-base", "--is-ancestor", a, b).returncode == 0


def _on_github(repo: Path, sha: str | None) -> bool:
    return bool(sha) and git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0 and bool(
        out(repo, "branch", "-r", "--contains", sha))


def _remote_head(repo: Path, branch: str) -> str:
    return out(repo, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}")


def _local_only(repo: Path, ref: str) -> int:
    return int(out(repo, "rev-list", "--count", ref, "--not", "--remotes") or 0)


def default_branch(repo: Path) -> str | None:
    ref = out(repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD")
    if ref and "/" in ref:
        return ref.split("/", 1)[1]
    for name in ("main", "master"):
        if _remote_head(repo, name):
            return name
    return None


def _worktree_of(repo: Path, branch: str) -> str:
    """The other working folder that has `branch` checked out, or "" (a branch out elsewhere is never moved: that
    folder's index would then undo the move with its next commit)."""
    where = out(repo, "for-each-ref", "--format=%(worktreepath)", f"refs/heads/{branch}")
    if not where:
        return ""
    try:
        return "" if Path(where).resolve() == repo.resolve() else where
    except OSError:
        return where


def ff_other_branches(repo: Path, current: str | None) -> list[str]:
    """Fast-forward every local branch that is not checked out (here or in another worktree) and is strictly behind
    its GitHub branch."""
    moved = []
    refs = out(repo, "for-each-ref",
               "--format=%(refname:short)%09%(upstream:short)%09%(upstream:track)%09%(worktreepath)", "refs/heads")
    for line in refs.splitlines():
        name, up, track, where = (line.split("\t") + ["", "", ""])[:4]
        if name == current or not up or track.strip() == "[gone]" or where:
            continue
        old, new = out(repo, "rev-parse", f"refs/heads/{name}"), out(repo, "rev-parse", "--verify", "-q",
                                                                      f"refs/remotes/{up}")
        if new and old != new and _is_ancestor(repo, old, new):
            if git(repo, "update-ref", "-m", "machine-sync: fast-forward", f"refs/heads/{name}", new, old).returncode == 0:
                moved.append(name)
    return moved


def _ff_current(repo: Path, name: str, s: RepoState, r: RepoResult) -> None:
    if not s.branch or not s.upstream or s.upstream_gone or not s.upstream_head or s.upstream_head == s.head:
        return
    if _is_ancestor(repo, s.head, s.upstream_head):
        done = git(repo, "merge", "--ff-only", "--no-overwrite-ignore", "--quiet", s.upstream_head)
        if done.returncode != 0:
            r.warnings.append(f"{name}: could not update {s.branch} from GitHub ({_first_line(done.stderr)})")
    elif not _is_ancestor(repo, s.upstream_head, s.head):
        r.warnings.append(f"{name}: {s.branch} split from GitHub: merge by hand")


def _first_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "no detail")


def _move_to(repo: Path, branch: str, target: str) -> str | None:
    """Put the checkout on `branch` at `target` (a commit GitHub has). Returns why not, or None."""
    if where := _worktree_of(repo, branch):
        return f"branch {branch} is checked out in another worktree ({where}): left as is, not switched"
    local = out(repo, "rev-parse", "--verify", "-q", f"refs/heads/{branch}")
    if local and local != target and not _is_ancestor(repo, target, local):
        if not _is_ancestor(repo, local, target) and _local_only(repo, local) > 0:
            return f"local branch {branch} has commits GitHub lacks: left as is, not switched"
        moved = git(repo, "update-ref", "-m", "machine-sync: follow", f"refs/heads/{branch}", target, local)
        if moved.returncode != 0:
            return f"could not move {branch} ({_first_line(moved.stderr)})"
    if local:
        done = git(repo, "switch", "--quiet", "--no-overwrite-ignore", branch)
    else:
        done = git(repo, "switch", "--quiet", "--no-overwrite-ignore", "-c", branch, target)
        if done.returncode == 0 and _remote_head(repo, branch):
            git(repo, "branch", "--quiet", "-u", f"origin/{branch}")
    if done.returncode != 0:
        if not local:
            git(repo, "branch", "-D", branch)  # created by us a moment ago, never checked out
        return f"could not switch to {branch} ({_first_line(done.stderr)})"
    return None


def _working_parts(s: RepoState, running: bool) -> list[str]:
    parts = []
    if s.uncommitted:
        parts.append(f"edits on this PC ({_plural(s.uncommitted, 'file')}): stayed here, not switched")
    if s.unpushed:
        parts.append(f"{_plural(s.unpushed, 'unpushed commit')} here: push them to share")
    if s.operation:
        parts.append(f"{s.operation} in progress")
    if running:
        parts.append("a daily task is running here")
    return parts


def sync_code(cfg: Settings, repo: str, peer: dict | None, frozen: bool, running: bool,
              in_use: set[Path] | frozenset = frozenset(), uv_cmd: list[str] | None = None,
              default_only: bool = False) -> RepoResult:
    """default_only: a repo the daily tasks run from (and the launcher): it follows the other PC only on the default
    branch, never onto a feature branch, so a daily run never starts on code that is not on main."""
    path = cfg.repo_path(repo)
    r = RepoResult(repo)
    if not (path / ".git").exists():
        r.line = "not on this PC"
        return r
    fetched = git(path, *NET, "fetch", "--all", "--prune", "--quiet", timeout=NET_TIMEOUT_S)
    s = read_repo(path)  # after the fetch: it may have pruned this branch's GitHub branch
    r.before = r.after = s.head
    r.state = s
    if fetched.returncode != 0:
        r.line = f"{_where(s.branch, s.head)}  could not reach GitHub"
        r.warnings.append(f"{repo}: could not reach GitHub ({_first_line(fetched.stderr)})")
        return r
    ff_other_branches(path, s.branch)
    notes: list[str] = []
    who = cfg.peer
    if frozen:
        notes.append("kept for today's daily run on this PC")
    elif s.uncommitted or s.unpushed or s.operation or running:
        notes += _working_parts(s, running)
        if not running:  # never any Git move under a running daily task
            _ff_current(path, repo, s, r)
        if peer and (peer.get("uncommitted") or peer.get("unpushed")):
            notes.append("work in progress on both PCs")
    else:
        leads = bool(peer) and peer.get("last_activity", 0) > s.last_activity and peer.get("head") != s.head
        branch = peer.get("branch") if leads else None
        default = default_branch(path) if leads and branch and default_only else None
        if default and branch != default:
            notes.append(f"{who} is on {branch}: not followed, this repo follows only {default} (daily tasks run "
                         "from it)")
            _ff_current(path, repo, s, r)
        elif leads and branch and _remote_head(path, branch):
            if _on_github(path, peer.get("head")):
                target = peer["head"]
            elif _on_github(path, peer.get("upstream_head")):
                target = peer["upstream_head"]
            else:
                target = None
            if target is None:
                notes.append(f"{who}'s commit is not on GitHub yet")
            elif s.branch == branch:
                if s.head != target and _is_ancestor(path, s.head, target):
                    done = git(path, "merge", "--ff-only", "--no-overwrite-ignore", "--quiet", target)
                    if done.returncode != 0:
                        r.warnings.append(f"{repo}: could not follow {who} ({_first_line(done.stderr)})")
            else:
                why = _move_to(path, branch, target)
                if why:
                    r.warnings.append(f"{repo}: {why}")
        elif s.upstream_gone and s.branch:
            default = default_branch(path)
            if default and default != s.branch and (head := _remote_head(path, default)):
                why = _move_to(path, default, head)
                if why:
                    r.warnings.append(f"{repo}: {why}")
                else:
                    notes.append(f"branch {s.branch} was deleted on GitHub: moved to {default} (local {s.branch} kept)")
            else:
                notes.append(f"branch {s.branch} was deleted on GitHub")
        elif s.branch is None:
            notes.append("detached HEAD: left as is")
        else:
            _ff_current(path, repo, s, r)
    end = read_repo(path)
    r.state = end
    r.after = end.head
    r.moved = end.head != s.head or end.branch != s.branch
    if r.moved:
        r.warnings += after_move(cfg, repo, s.head, end.head, set(in_use), uv_cmd)
    if peer and peer.get("unpushed") and not any("unpushed commit" in n and who in n for n in notes):
        notes.append(f"{who} has {_plural(peer['unpushed'], 'unpushed commit')}: push them to share")
    if not notes:
        if peer and end.head == peer.get("head") and end.branch == peer.get("branch"):
            notes.append(f"same as {who}")
        elif r.moved:
            notes.append("updated")
    if end.untracked:
        notes.append(f"{_plural(end.untracked, 'untracked file')} here (not in Git: commit or ignore them to share)")
    r.line = "  ".join([_where(end.branch, end.head), *notes]) if notes else _where(end.branch, end.head)
    return r


# ----------------------------------------------------------------- after a move: libraries
_PENDING_LOCK = threading.Lock()  # repos run in parallel threads; they share pending_uv.json


def _pending_path(cfg: Settings) -> Path:
    return cfg.sync_dir / "pending_uv.json"


def _load_pending(cfg: Settings) -> list[str]:
    try:
        return json.loads(_pending_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _save_pending(cfg: Settings, pending: list[str]) -> None:
    cfg.sync_dir.mkdir(parents=True, exist_ok=True)
    _pending_path(cfg).write_text(json.dumps(sorted(set(pending))), encoding="utf-8")


def _uv_sync(app: Path, in_use: set[Path], uv_cmd: list[str] | None) -> str | None:
    """Sync app/.venv to app/requirements.lock.txt. Returns why it waits, or None when done."""
    venv = app / ".venv"
    if not (venv / "Scripts" / "python.exe").exists():
        return f"{app}: requirements.lock.txt changed but there is no .venv: install its libraries by hand"
    if venv.resolve() in in_use:
        return f"{app}: requirements.lock.txt changed: close the app using its .venv; the sync updates it after"
    if not uv_cmd:
        return f"{app}: requirements.lock.txt changed but uv was not found: run uv pip sync by hand"
    done = subprocess.run([*uv_cmd, "pip", "sync", "--python", str(venv / "Scripts" / "python.exe"),
                           "requirements.lock.txt"], cwd=app, capture_output=True, text=True, creationflags=NO_WINDOW)
    if done.returncode != 0:
        return f"{app}: uv pip sync failed ({_first_line(done.stderr)})"
    return None


def _default_uv() -> list[str] | None:
    uv = shutil.which("uv")
    return [uv] if uv else None


def after_move(cfg: Settings, repo: str, before: str, after: str, in_use: set[Path],
               uv_cmd: list[str] | None = None) -> list[str]:
    path = cfg.repo_path(repo)
    uv_cmd = uv_cmd if uv_cmd is not None else _default_uv()
    lines, waiting = [], []
    for changed in out(path, "diff", "--name-only", before, after).splitlines():
        folder = Path(changed).parent
        where = f"{repo}\\{folder}" if str(folder) != "." else repo
        if changed.endswith("requirements.lock.txt"):
            app = (path / folder).resolve()
            why = _uv_sync(app, in_use, uv_cmd)
            if why:  # every failure waits in pending_uv.json: retried each run, and a daily start is refused meanwhile
                lines.append(why)
                waiting.append(str(app))
        elif changed.endswith("package-lock.json"):
            lines.append(f"{where}: package-lock.json changed: run npm ci in {where}")
        elif changed.endswith(".python-version"):
            lines.append(f"{where}: .python-version changed: rebuild that .venv by hand")
    if waiting:
        with _PENDING_LOCK:
            _save_pending(cfg, _load_pending(cfg) + waiting)
    return lines


def pending_uv(cfg: Settings) -> list[str]:
    """App folders whose libraries were not updated after a code change (MachineSync\\pending_uv.json)."""
    return _load_pending(cfg)


def retry_pending_uv(cfg: Settings, in_use: set[Path], uv_cmd: list[str] | None = None) -> list[str]:
    """Libraries not updated yet (an app had its .venv open, uv failed or was missing, no .venv): try again."""
    uv_cmd = uv_cmd if uv_cmd is not None else _default_uv()
    still, lines = [], []
    for app in _load_pending(cfg):
        why = _uv_sync(Path(app), in_use, uv_cmd)
        if why:
            still.append(app)
            lines.append(why)
    _save_pending(cfg, still)
    return lines
