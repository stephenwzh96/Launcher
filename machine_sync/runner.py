"""One run on this PC (design, "One run"): code step, data step, status. Run every 5 minutes, at logon, unlock and
wake by the "Machine sync" scheduled task."""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import NOTE_FORMAT
from . import claims as day_claims
from .code_sync import RepoResult, repo_note, retry_pending_uv, sync_code
from .daily import (busy_repos, code_frozen, load_daily_tasks, read_claims, record_claim, running_tasks,
                    venvs_in_use)
from .data_sync import ImportResult, load_state, read_alive, read_note, sync_data
from .procs import Proc, processes
from .selfupdate import self_update
from .settings import Settings
from .status import log, render, write_status

LOCK_STALE_S = 3600


def _pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    import ctypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() == 5  # access denied: it exists
    try:
        code = ctypes.c_ulong()
        return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259  # STILL_ACTIVE
    finally:
        k32.CloseHandle(handle)


def _take_lock(cfg: Settings) -> bool:
    cfg.sync_dir.mkdir(parents=True, exist_ok=True)
    lock = cfg.sync_dir / "run.lock"
    for _ in range(2):
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid, age = int(lock.read_text().strip() or 0), time.time() - lock.stat().st_mtime
            except (OSError, ValueError):
                pid, age = 0, 0.0
            if pid and _pid_alive(pid) and age < LOCK_STALE_S:
                return False
            lock.unlink(missing_ok=True)
            continue
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return True
    return False


def _refresh_claims(cfg: Settings, tasks: list[dict], now: datetime) -> None:
    """Who holds today's claims on GitHub, for the code freeze and the launcher's reminder."""
    launcher = cfg.repo_path("Marco/launcher")
    if not (launcher / ".git").exists():
        return
    day = now.strftime("%Y-%m-%d")
    for name in sorted({t["claim"] for t in tasks if t.get("claim")}):
        held = day_claims.holder(launcher, name, day)
        if held.ok and held.holder:
            record_claim(cfg.sync_dir, name, day, held.holder, held.at or "")


def run_once(cfg: Settings, now: datetime | None = None, allow_deletes: bool = False, update_frozen: bool = False,
             procs: list[Proc] | None = None, tasks: list[dict] | None = None,
             uv_cmd: list[str] | None = None) -> str:
    now = now or datetime.now()
    if not _take_lock(cfg):
        return f"Sync on {cfg.machine}, {now:%d %b %H:%M}: previous run still going, skipped\n"
    try:
        return _run(cfg, now, allow_deletes, update_frozen, procs, tasks, uv_cmd)
    except Exception as err:  # noqa: BLE001 - a scheduled run: record why and let the next run try again
        log(cfg, now, [f"ERROR {type(err).__name__}: {err}"])
        raise
    finally:
        (cfg.sync_dir / "run.lock").unlink(missing_ok=True)


def _run(cfg: Settings, now: datetime, allow_deletes: bool, update_frozen: bool, procs: list[Proc] | None,
         tasks: list[dict] | None, uv_cmd: list[str] | None) -> str:
    warnings: list[str] = []
    peer_note = read_note(cfg, cfg.peer)
    shown_note = peer_note
    if peer_note and peer_note.get("format", 0) > NOTE_FORMAT:
        warnings.append(f"the {cfg.peer} runs a newer sync tool: this PC does not follow or import from it until its "
                        "own tool updates (from the launcher's main)")
        peer_note = None
    tasks = load_daily_tasks(cfg) if tasks is None else tasks
    procs = processes() if procs is None else procs
    running_ids = running_tasks(tasks, procs)
    running_repos = busy_repos(cfg, [t for t in tasks if t["id"] in running_ids])
    busy = busy_repos(cfg, tasks)
    in_use = venvs_in_use(procs)
    try:
        _refresh_claims(cfg, tasks, now)
    except OSError as err:
        warnings.append(f"could not read today's claim from GitHub ({err})")
    frozen = code_frozen(cfg, now) and not update_frozen
    peer_repos = (peer_note or {}).get("repos") or {}

    def one(repo: str) -> RepoResult:
        return sync_code(cfg, repo, peer_repos.get(repo), frozen=frozen and repo in busy,
                         running=repo in running_repos, in_use=in_use, uv_cmd=uv_cmd)

    with ThreadPoolExecutor(max_workers=len(cfg.repos) or 1) as pool:  # repos are independent: fetch in parallel
        results: list[RepoResult] = list(pool.map(one, cfg.repos))
    for r in results:
        warnings += r.warnings
    warnings += retry_pending_uv(cfg, in_use, uv_cmd)
    if updated := self_update(cfg):
        warnings.append(updated)
    repos_note = {r.repo: repo_note(r.state, r.repo in running_repos) for r in results if r.state}
    state = load_state(cfg)
    res: ImportResult = sync_data(cfg, state, peer_note, now.timestamp(), frozen_repos=running_repos,
                                  allow_deletes=allow_deletes,
                                  note_extra={"repos": repos_note, "claims": read_claims(cfg.sync_dir)})
    text = render(cfg, now, results, res, state, shown_note, warnings, read_claims(cfg.sync_dir),
                  peer_seen=read_alive(cfg, cfg.peer))
    write_status(cfg, now, text)
    return text
