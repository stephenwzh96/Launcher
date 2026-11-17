"""Daily tasks (launcher tasks.yaml entries with `claim`), which repos they use, whether one is running here, the
day's claim as last seen, and the code freeze on the PC that holds it (design, "Daily tasks and freezes")."""
from __future__ import annotations

import json
import os
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
print(json.dumps([{"id": t.id, "claim": getattr(t, "claim", None), "cwd": str(t.resolved_cwd()),
                   "cmd": t.resolved_cmd()} for t in tasks if getattr(t, "claim", None)]))
"""


def load_daily_tasks(cfg: Settings) -> list[dict]:
    """The daily tasks from the launcher's tasks.yaml, read through the launcher's own venv (it has the YAML
    reader). Falls back to the last good copy in MachineSync\\tasks.json."""
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
        if isinstance(tasks, list):
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


def running_tasks(tasks: list[dict], procs: list[Proc]) -> set[str]:
    """Daily tasks with a process whose command line holds all of the task's arguments."""
    lines = [_norm(p.cmdline) for p in procs if p.cmdline]
    running = set()
    for task in tasks:
        args = [_norm(a) for a in task["cmd"][1:]]
        if args and any(all(a in line for a in args) for line in lines):
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
