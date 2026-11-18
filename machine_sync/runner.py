"""One run on this PC (design, "One run"): code step, data step, status. Run every 5 minutes, at logon, unlock and
wake by the "Machine sync" scheduled task."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import NOTE_FORMAT, runlock
from . import claims as day_claims
from .code_sync import RepoResult, repo_note, retry_pending_uv, sync_code
from .daily import (busy_repos, code_frozen, load_daily_tasks, read_claims, record_claim, running_tasks,
                    venvs_in_use)
from .data_sync import ImportResult, clock_skew, load_state, read_alive, read_note, sync_data
from .procs import Proc, processes
from .selfupdate import self_update
from .settings import Settings
from .status import log, render, write_status

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
    if not runlock.acquire(cfg.sync_dir):
        return (f"Sync on {cfg.machine}, {now:%d %b %H:%M}: previous run still going (or a daily task is being "
                "started), skipped\n")
    try:
        return _run(cfg, now, allow_deletes, update_frozen, procs, tasks, uv_cmd)
    except Exception as err:  # noqa: BLE001 - a scheduled run: record why and let the next run try again
        log(cfg, now, [f"ERROR {type(err).__name__}: {err}"])
        raise
    finally:
        runlock.release(cfg.sync_dir)


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
    busy = busy_repos(cfg, tasks)
    if procs is None:  # unknown: assume a daily task may be running (fail closed)
        warnings.append("could not list running processes: the daily tasks' repos are held this run")
        procs, running_ids = [], {t["id"] for t in tasks}
    else:
        running_ids = running_tasks(tasks, procs)
    # any daily task running holds every repo the daily tasks use (Start of Day reads IBKR's settlements, the IBKR
    # cycle reads Trend's envelopes): no Git moves, no imports, no deletions recorded there
    running_repos = busy if running_ids else set()
    in_use = venvs_in_use(procs)
    try:
        _refresh_claims(cfg, tasks, now)
    except OSError as err:
        warnings.append(f"could not read today's claim from GitHub ({err})")
    names = {t["claim"] for t in tasks if t.get("claim")} or None
    frozen = code_frozen(cfg, now, names) and not update_frozen
    peer_repos = (peer_note or {}).get("repos") or {}

    def one(repo: str) -> RepoResult:
        try:
            return sync_code(cfg, repo, peer_repos.get(repo), frozen=frozen and repo in busy,
                             running=repo in running_repos, in_use=in_use, uv_cmd=uv_cmd)
        except Exception as err:  # noqa: BLE001 - one repo's trouble must not stop the others or the data
            return RepoResult(repo, line=f"error: {type(err).__name__}: {err}",
                              warnings=[f"{repo}: the code step failed ({type(err).__name__}: {err})"])

    with ThreadPoolExecutor(max_workers=len(cfg.repos) or 1) as pool:  # repos are independent: fetch in parallel
        results: list[RepoResult] = list(pool.map(one, cfg.repos))
    for r in results:
        warnings += r.warnings
    warnings += retry_pending_uv(cfg, in_use, uv_cmd)
    hold = ("a daily task is running here" if running_ids else
            "this PC's code is kept for today's daily run until 09:00" if frozen else None)
    if updated := self_update(cfg, hold=hold):
        warnings.append(updated)
    repos_note = {r.repo: repo_note(r.state, r.repo in running_repos) for r in results if r.state}
    state = load_state(cfg)
    try:
        res: ImportResult = sync_data(cfg, state, peer_note, now.timestamp(), frozen_repos=running_repos,
                                      allow_deletes=allow_deletes,
                                      note_extra={"repos": repos_note, "claims": read_claims(cfg.sync_dir)})
    except Exception as err:  # noqa: BLE001 - still write the status; the next run tries again
        res = ImportResult(skipped=[f"the data step failed: {type(err).__name__}: {err}"])
        warnings.append(f"the data step failed ({type(err).__name__}: {err}); next run tries again")
    if skew := clock_skew(cfg, state, shown_note, read_alive(cfg, cfg.peer), now.timestamp()):
        warnings.append(skew)
    text = render(cfg, now, results, res, state, shown_note, warnings, read_claims(cfg.sync_dir),
                  peer_seen=read_alive(cfg, cfg.peer))
    write_status(cfg, now, text)
    return text
