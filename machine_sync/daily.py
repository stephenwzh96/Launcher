"""Daily tasks (launcher tasks.yaml entries with `claim`), which repos they use, whether one is running here, the
day's claim as last seen, and the code freeze on the PC that holds it (design, "Daily tasks and freezes")."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .gitops import NO_WINDOW
from .procs import Proc
from .settings import FREEZE_UNTIL_HOUR, Settings

CLAIM_FILE = "daily_claim.json"
CLAIM_DAYS_KEPT = 2

_DUMP = """
import json, sys
from pathlib import Path
here = Path.cwd()
sys.path.insert(0, str(here))
from config import load_tasks
tasks = load_tasks(here / "tasks.yaml")
def progress(t):
    f = t.resolved_progress_file() if hasattr(t, "resolved_progress_file") else None
    return str(f) if f else None
print(json.dumps([{"id": t.id, "claim": getattr(t, "claim", None), "cwd": str(t.resolved_cwd()),
                   "cmd": t.resolved_cmd(), "progress_file": progress(t)} for t in tasks]))
"""


def load_daily_tasks(cfg: Settings) -> list[dict]:
    """Every Start of Day task in the launcher's tasks.yaml (all of them are daily jobs, claimed or not), read
    through the launcher's own venv (it has the YAML reader). Falls back to the last good copy in
    MachineSync\\tasks.json, which an empty answer never overwrites."""
    cache = cfg.sync_dir / "tasks.json"
    launcher = cfg.repo_path("Marco/launcher")
    python = launcher / ".venv" / "Scripts" / "python.exe"
    if python.exists():
        try:
            done = subprocess.run([str(python), "-I", "-c", _DUMP], cwd=launcher, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW)
            tasks = json.loads(done.stdout) if done.returncode == 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            tasks = None
        if isinstance(tasks, list) and tasks:
            cfg.sync_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(tasks), encoding="utf-8")
            return tasks
    try:
        return json.loads(cache.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _norm(text: str) -> str:
    return text.replace("/", "\\").replace('"', "").lower()


def _repo_of_path(cfg: Settings, path: Path) -> str | None:
    try:
        rel = path.resolve().relative_to(cfg.home.resolve()).as_posix()
    except ValueError:
        return None
    for repo in sorted(cfg.repos, key=len, reverse=True):
        if rel == repo or rel.startswith(repo + "/"):
            return repo
    return None


def busy_repos(cfg: Settings, tasks: list[dict]) -> set[str]:
    """Every repo a daily task's folder or command line points into."""
    repos = set()
    for task in tasks:
        for token in [task["cwd"], *task["cmd"]]:
            if "/" in token or "\\" in token:
                repo = _repo_of_path(cfg, Path(token))
                if repo:
                    repos.add(repo)
    return repos


def _tokens(cmdline: str) -> list[str]:
    """A Windows command line's arguments, unquoted and normalised (backslashes, lower case)."""
    try:
        parts = shlex.split(cmdline, posix=False)
    except ValueError:  # an unbalanced quote
        parts = cmdline.split()
    return [_norm(p) for p in parts]


def _signature(cmd: list[str]) -> tuple[str, list[str]] | None:
    """What identifies a daily task's process however it was started (the launcher's absolute paths, or a terminal's
    relative ones): ("module", ["-m", module, subcommand]) or ("script", [file name])."""
    args = cmd[1:]
    if len(args) >= 2 and args[0] == "-m":
        sig = ["-m", _norm(args[1])]
        if len(args) >= 3 and not args[2].startswith("-"):
            sig.append(_norm(args[2]))
        return "module", sig
    if args and args[0].lower().endswith(".py"):
        return "script", [_norm(args[0]).rsplit("\\", 1)[-1]]
    return None


def _matches(sig: tuple[str, list[str]], tokens: list[str]) -> bool:
    kind, want = sig
    if kind == "module":
        n = len(want)
        return any(tokens[i:i + n] == want for i in range(len(tokens) - n + 1))
    runner = tokens[0].rsplit("\\", 1)[-1] if tokens else ""
    if not (runner.startswith("python") or runner in ("py.exe", "py")):
        return False  # an editor with the script open is not the task
    return any(t.rsplit("\\", 1)[-1] == want[0] for t in tokens[1:])


def _progress_running(path: str | None, pids: set[int]) -> bool:
    """The task's progress file (Trend's sod_progress.json) says running, and its process is alive."""
    if not path:
        return False
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return doc.get("state") == "running" and int(doc.get("pid") or 0) in pids
    except (OSError, ValueError, TypeError, AttributeError):
        return False


def running_tasks(tasks: list[dict], procs: list[Proc]) -> set[str]:
    """Daily tasks running on this PC, started by the launcher or from a terminal: a process whose command line holds
    all of the task's arguments, or runs its script (by file name) or module and subcommand (`-m src.operations
    run`) from any folder; or the task's progress file says running and names a live process."""
    lines = [_norm(p.cmdline) for p in procs if p.cmdline]
    tokens = [_tokens(p.cmdline) for p in procs if p.cmdline]
    pids = {p.pid for p in procs}
    running = set()
    for task in tasks:
        args = [_norm(a) for a in task["cmd"][1:]]
        sig = _signature(task["cmd"])
        if (args and any(all(a in line for a in args) for line in lines))                 or (sig and any(_matches(sig, t) for t in tokens))                 or _progress_running(task.get("progress_file"), pids):
            running.add(task["id"])
    return running


def venvs_in_use(procs: list[Proc]) -> set[Path]:
    """Virtual environments a running process was started from (never `uv pip sync`ed while in use)."""
    used = set()
    for p in procs:
        if not p.exe:
            continue
        exe = Path(p.exe)
        venv = exe.parent.parent
        if exe.parent.name.lower() == "scripts" and (
                ".venv" in {part.lower() for part in exe.parts} or (venv / "pyvenv.cfg").exists()):
            used.add(venv.resolve())
    return used


# ----------------------------------------------------------------- the day's claim as last seen
def read_claims(sync_dir: Path) -> list[dict]:
    try:
        return json.loads((sync_dir / CLAIM_FILE).read_text(encoding="utf-8")).get("claims", [])
    except (OSError, ValueError, AttributeError):
        return []


def record_claim(sync_dir: Path, claim: str, day: str, holder: str, at: str) -> None:
    """Remember who holds `claim` on `day` (the launcher after claiming, the sync after looking on GitHub)."""
    claims = [c for c in read_claims(sync_dir) if not (c["claim"] == claim and c["day"] == day)]
    claims.append({"claim": claim, "day": day, "holder": holder, "at": at})
    days = sorted({c["day"] for c in claims})[-CLAIM_DAYS_KEPT:]
    claims = sorted((c for c in claims if c["day"] in days), key=lambda c: (c["day"], c["claim"]))
    sync_dir.mkdir(parents=True, exist_ok=True)
    tmp = sync_dir / (CLAIM_FILE + ".msync-tmp")
    tmp.write_text(json.dumps({"claims": claims}, indent=1), encoding="utf-8")
    os.replace(tmp, sync_dir / CLAIM_FILE)


DEFAULT_CLAIMS = {"daily"}  # when tasks.yaml cannot be read, still honour the daily tasks' claim


def holds_claim_today(cfg: Settings, now: datetime, names: set[str] | None = None) -> bool:
    today, names = now.strftime("%Y-%m-%d"), names or DEFAULT_CLAIMS
    return any(c["day"] == today and c["holder"] == cfg.machine and c["claim"] in names
               for c in read_claims(cfg.sync_dir))


def code_frozen(cfg: Settings, now: datetime, names: set[str] | None = None) -> bool:
    """This PC holds a daily-task claim (`names`), and `now` is between that claim and 09:00 the day after its day.
    Other claim names (tests) never freeze code."""
    names = names or DEFAULT_CLAIMS
    for c in read_claims(cfg.sync_dir):
        if c["holder"] != cfg.machine or c["claim"] not in names:
            continue
        try:
            start = datetime.fromisoformat(c["at"])
            day = datetime.strptime(c["day"], "%Y-%m-%d")
        except ValueError:
            continue
        if start <= now < day + timedelta(days=1, hours=FREEZE_UNTIL_HOUR):
            return True
    return False
