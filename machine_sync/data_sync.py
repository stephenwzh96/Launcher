"""Two-way data (design, "Data step"): each PC records a version per data file (content hash, change stamp, the stamp
it replaced, deleted or not), publishes all of them in its note, keeps in its outbox only the files the other PC
lacks and that are newer here, and takes the other PC's newer versions. The newer change wins on both PCs; a file
this PC had changed is backed up before it is replaced or deleted."""
from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import NOTE_FORMAT
from .data_files import SKIP_DIRS, data_files, hash_file, is_sqlite, sqlite_open
from .gitops import git
from .settings import BACKUP_DAYS, BRAKE_FRACTION, BRAKE_MIN, STABLE_S, TOMBSTONE_DAYS, Settings

OUTBOX_OWN = {"_state", "_tools", ".stfolder", ".stignore", ".stversions"}  # never data, never removed
CLASH_KEEP_DAYS = 7


@dataclass
class ImportResult:
    taken: int = 0
    deleted: int = 0
    waiting: int = 0
    skipped: list[str] = field(default_factory=list)
    clashes: list[str] = field(default_factory=list)
    held_deletes: int = 0
    exported: int = 0


# ----------------------------------------------------------------- state and notes
def _write_json(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".msync-tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def load_state(cfg: Settings) -> dict:
    try:
        state = json.loads((cfg.sync_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    for key, empty in (("files", {}), ("outbox", {}), ("clashes", []), ("unstable", []), ("missing", {}),
                       ("errors", [])):
        state.setdefault(key, empty)
    for e in state["files"].values():  # state written before version vectors
        if "vv" not in e:
            e["vv"] = {e["m"]: e["t"]}
            e.pop("b", None)
    return state


def save_state(cfg: Settings, state: dict) -> None:
    _write_json(cfg.sync_dir / "state.json", state)


def read_note(cfg: Settings, machine: str) -> dict | None:
    try:
        return json.loads(cfg.note_path(machine).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def make_note(cfg: Settings, state: dict, now: float, extra: dict | None = None) -> dict:
    files = {rel: [e["h"], e["t"], e["m"], e["vv"], e["del"]] for rel, e in state["files"].items()}
    return {"format": NOTE_FORMAT, "machine": cfg.machine, "written": now, "files": files,
            "clashes": state["clashes"], **(extra or {})}


def write_note(cfg: Settings, note: dict) -> None:
    _write_json(cfg.note_path(cfg.machine), note)


def _alive_path(cfg: Settings, machine: str) -> Path:
    return cfg.note_path(machine).with_name(f"{machine}.alive.json")


def read_alive(cfg: Settings, machine: str) -> float | None:
    """When `machine` last ran (its small heartbeat file, rewritten every run)."""
    try:
        return float(json.loads(_alive_path(cfg, machine).read_text(encoding="utf-8"))["written"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _same_note(a: dict | None, b: dict) -> bool:
    return a is not None and {k: v for k, v in a.items() if k != "written"} == {
        k: v for k, v in b.items() if k != "written"}


def _key(v: dict) -> tuple[float, str]:
    return (v["t"], v["m"])


def _version(raw: list) -> dict:
    """A note entry [hash, stamp, machine, version vector, deleted]. The vector holds, per PC, the stamp of the
    latest change made on that PC which this version includes: a clash is a change of ours the other side never saw."""
    vv = raw[3] if isinstance(raw[3], dict) else {raw[2]: raw[1]}
    return {"h": raw[0], "t": raw[1], "m": raw[2], "vv": vv, "del": bool(raw[4])}


def _merge(a: dict, b: dict) -> dict:
    return {k: max(a.get(k, 0.0), b.get(k, 0.0)) for k in {*a, *b}}


def _safe_rel(cfg: Settings, rel: str) -> bool:
    """A note path this PC may write: relative, no '..', inside one of the repos or plain folders."""
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in rel or "\\" in rel or any(p in ("", ".", "..") for p in parts):
        return False
    return _root_of(cfg, rel) is not None


def _repo_of(cfg: Settings, rel: str) -> str | None:
    for repo in sorted(cfg.repos, key=len, reverse=True):
        if rel.startswith(repo + "/"):
            return repo
    return None


def _root_of(cfg: Settings, rel: str) -> Path | None:
    repo = _repo_of(cfg, rel)
    if repo:
        return cfg.repo_path(repo)
    top = rel.split("/", 1)[0]
    return cfg.home / top if top in cfg.plain_roots else None


# ----------------------------------------------------------------- scan this PC
def scan(cfg: Settings, state: dict, now: float, frozen_repos: set[str] = frozenset()) -> dict:
    """Record this PC's changes. A file still being written (changed in the last STABLE_S seconds) or unreadable is
    left for a later run. A file is deleted only when it has been missing on two runs at least STABLE_S apart (a
    job rewriting its output folder is not a deletion), and never in a repo a daily task is using right now."""
    files = data_files(cfg)
    entries, unstable, errors, missing = state["files"], [], [], state["missing"]
    for rel, path in files.items():
        missing.pop(rel, None)
        try:
            st = path.stat()
            e = entries.get(rel)
            if e and not e["del"] and e["size"] == st.st_size and e["mt"] == st.st_mtime_ns:
                continue
            if now - st.st_mtime < STABLE_S:
                unstable.append(rel)
                continue
            h = hash_file(path)
        except OSError as err:  # locked or vanished: try again next run, never treat as a change
            unstable.append(rel)
            errors.append(f"{rel}: could not read ({err.strerror or err})")
            continue
        if e and not e["del"] and e["h"] == h:
            e["size"], e["mt"] = st.st_size, st.st_mtime_ns
            continue
        stamp = min(st.st_mtime, now) if e is None else now  # first sight: its own time; any later change: now
        vv = dict(e["vv"]) if e else {}
        vv[cfg.machine] = stamp
        entries[rel] = {"h": h, "t": stamp, "m": cfg.machine, "vv": vv, "del": False,
                        "size": st.st_size, "mt": st.st_mtime_ns}
    for rel, e in list(entries.items()):
        if e["del"]:
            if now - e["t"] > TOMBSTONE_DAYS * 86400:
                del entries[rel]
            continue
        if rel in files:
            continue
        root = _root_of(cfg, rel)
        if root is None or not root.exists() or _repo_of(cfg, rel) in frozen_repos:
            continue  # a whole repo or folder missing, or a repo in use by a daily task: never deletions
        if (cfg.home / rel).exists():
            del entries[rel]  # still here but no longer data (now tracked or excluded)
            missing.pop(rel, None)
            continue
        first = missing.setdefault(rel, now)
        if now - first < STABLE_S or first == now:
            continue
        missing.pop(rel)
        vv = dict(e["vv"])
        vv[cfg.machine] = now
        entries[rel] = {"h": None, "t": now, "m": cfg.machine, "vv": vv, "del": True, "size": 0, "mt": 0}
    for rel in [r for r in missing if r not in entries or entries[r]["del"]]:
        missing.pop(rel)
    state["unstable"], state["errors"] = unstable, errors
    return state


# ----------------------------------------------------------------- import from the other PC
def _ignored_here(cfg: Settings, rels: list[str]) -> set[str]:
    """The repo paths among rels that this PC's Git ignores (the only ones the sync may write)."""
    allowed: set[str] = set()
    by_repo: dict[str, list[str]] = {}
    for rel in rels:
        repo = _repo_of(cfg, rel)
        if repo is None:
            allowed.add(rel)  # plain folders
        else:
            by_repo.setdefault(repo, []).append(rel[len(repo) + 1:])
    for repo, inside in by_repo.items():
        root = cfg.repo_path(repo)
        if not (root / ".git").exists():
            continue
        listing = git(root, "check-ignore", "--stdin", "-z", input="\0".join(inside) + "\0").stdout
        allowed |= {f"{repo}/{r}" for r in listing.split("\0") if r}
    return allowed


def _copy_atomic(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".msync-tmp")
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except OSError:
        tmp.unlink(missing_ok=True)
        raise


def _backup_path(cfg: Settings, rel: str, now: float) -> Path:
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    target = cfg.sync_dir / "backup" / day / rel
    if target.exists():
        target = target.with_name(f"{target.stem}.{datetime.fromtimestamp(now):%H%M%S}{target.suffix}")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _replace(cfg: Settings, rel: str, staged: Path | None, now: float, keep_old: bool) -> Path | None:
    """Put `staged` at rel (or delete rel when staged is None). keep_old: first move the current file into the
    backup folder by renaming it (same disk), so a file held open fails cleanly and leaves no copy behind; on any
    failure the old file is put back. Returns the backup's path, if one was kept."""
    dst = cfg.home / rel
    tmp = dst.with_name(dst.name + ".msync-tmp")
    backup = None
    try:
        if staged is not None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged, tmp)
        if dst.exists() and (keep_old or staged is None):
            backup = _backup_path(cfg, rel, now)
            os.replace(dst, backup)
        if staged is not None:
            os.replace(tmp, dst)
    except OSError:
        if backup is not None and backup.exists() and not dst.exists():
            os.replace(backup, dst)
        tmp.unlink(missing_ok=True)
        raise
    return backup


def _changed_since_scan(cfg: Settings, rel: str, e: dict | None) -> bool:
    """The file was written after this run's scan (or appeared, or reappeared): never replace it on old facts."""
    try:
        st = (cfg.home / rel).stat()
    except OSError:
        return e is not None and not e["del"]  # the scan saw it; now it is gone
    return e is None or e["del"] or st.st_size != e["size"] or st.st_mtime_ns != e["mt"]


def import_from_peer(cfg: Settings, state: dict, peer_note: dict | None, frozen_repos: set[str],
                     allow_deletes: bool, now: float) -> ImportResult:
    res = ImportResult()
    entries, unstable = state["files"], set(state["unstable"])
    candidates = []
    for rel, raw in ((peer_note or {}).get("files") or {}).items():
        if not _safe_rel(cfg, rel):
            res.skipped.append(f"{rel!r}: not inside a synced folder on this PC, ignored")
            continue
        p, e = _version(raw), entries.get(rel)
        if e is not None and e["del"] == p["del"] and (p["del"] or e["h"] == p["h"]):
            e["vv"] = _merge(e["vv"], p["vv"])  # same content: one version, both PCs' changes included
            if _key(p) > _key(e):
                e.update(t=p["t"], m=p["m"])
            continue
        if (e is None and p["del"]) or (e is not None and _key(e) >= _key(p)):
            continue
        candidates.append((rel, p, e))
    allowed = _ignored_here(cfg, [rel for rel, _, _ in candidates])
    takes, deletes = [], []
    for rel, p, e in candidates:
        repo = _repo_of(cfg, rel)
        if repo in frozen_repos:
            res.skipped.append(f"{rel}: held while a daily task runs here")
            continue
        if rel in unstable:
            res.skipped.append(f"{rel}: changing here right now")
            continue
        if repo and rel not in allowed:
            res.skipped.append(f"{rel}: tracked by Git on this PC, left to Git")
            continue
        # a clash: this PC's copy holds a change of its own that the incoming version was not made from
        clash = e is not None and not e["del"] and e["vv"].get(cfg.machine, 0.0) > p["vv"].get(cfg.machine, 0.0)
        if p["del"]:
            deletes.append((rel, p, clash))
            continue
        staged = cfg.peer_outbox / rel
        try:
            arrived = staged.is_file() and hash_file(staged) == p["h"]
        except OSError:
            arrived = False
        if not arrived:
            res.waiting += 1
            continue
        if is_sqlite(staged) and sqlite_open(cfg.home / rel):
            res.skipped.append(f"{rel}: database open on this PC")
            continue
        takes.append((rel, p, clash, staged))
    live = sum(1 for e in entries.values() if not e["del"])
    if len(deletes) > max(BRAKE_MIN, BRAKE_FRACTION * live) and not allow_deletes:
        res.held_deletes, deletes = len(deletes), []
    for rel, p, clash, staged in takes:
        if _changed_since_scan(cfg, rel, entries.get(rel)):
            res.skipped.append(f"{rel}: changed on this PC during this run, next run decides")
            continue
        try:
            backup = _replace(cfg, rel, staged, now, keep_old=clash)
        except OSError as err:
            res.skipped.append(f"{rel}: could not write, in use? ({err.strerror or err})")
            continue
        st = (cfg.home / rel).stat()
        entries[rel] = {"h": p["h"], "t": p["t"], "m": p["m"], "vv": dict(p["vv"]), "del": False,
                        "size": st.st_size, "mt": st.st_mtime_ns}
        res.taken += 1
        if clash:
            _record_clash(state, res, rel, p, backup, now)
    for rel, p, clash in deletes:
        if _changed_since_scan(cfg, rel, entries.get(rel)):
            res.skipped.append(f"{rel}: changed on this PC during this run, next run decides")
            continue
        try:
            backup = _replace(cfg, rel, None, now, keep_old=True)
        except OSError as err:
            res.skipped.append(f"{rel}: could not delete, in use? ({err.strerror or err})")
            continue
        entries[rel] = {"h": None, "t": p["t"], "m": p["m"], "vv": dict(p["vv"]), "del": True, "size": 0, "mt": 0}
        res.deleted += 1
        if clash:
            _record_clash(state, res, rel, p, backup, now)
    return res


def _record_clash(state: dict, res: ImportResult, rel: str, p: dict, backup: Path | None, now: float) -> None:
    what = "deleted" if p["del"] else "changed"
    res.clashes.append(f"{rel}: changed on both PCs; {p['m']}'s {what} version kept, this PC's copy in {backup}")
    state["clashes"].append({"path": rel, "when": now, "kept": p["m"], "backup": str(backup) if backup else None})


# ----------------------------------------------------------------- this PC's outbox
def _outbox_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        if Path(dirpath) == root:
            dirnames[:] = [d for d in dirnames if d not in OUTBOX_OWN]
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if rel.split("/")[0] not in OUTBOX_OWN:
                yield rel, path


def refresh_outbox(cfg: Settings, state: dict, peer_note: dict | None) -> int:
    """Keep exactly the files the other PC lacks and that are newer here; remove the rest. With no readable note
    from the other PC the outbox is left as it is: nothing new is sent (it may already have every file) and nothing
    already on its way is thrown away."""
    if peer_note is None:
        return 0
    peer_files = peer_note.get("files") or {}
    unstable = set(state["unstable"])
    wanted: dict[str, dict] = {}
    for rel, e in state["files"].items():
        if e["del"] or rel in unstable:
            continue
        raw = peer_files.get(rel)
        if raw is not None:
            p = _version(raw)
            if (not p["del"] and p["h"] == e["h"]) or _key(p) > _key(e):
                continue
        src = cfg.home / rel
        if is_sqlite(src) and sqlite_open(src):
            continue
        wanted[rel] = e
    root, record, written = cfg.own_outbox, state["outbox"], 0
    for rel, e in wanted.items():
        dst, src = root / rel, cfg.home / rel
        try:
            if dst.is_file() and (record.get(rel) == e["h"] or hash_file(dst) == e["h"]):
                record[rel] = e["h"]
                continue
            _copy_atomic(src, dst)
            st = src.stat()
            if st.st_size != e["size"] or st.st_mtime_ns != e["mt"] or hash_file(dst) != e["h"]:
                dst.unlink(missing_ok=True)  # changed while it was copied: next run
                record.pop(rel, None)
                continue
        except OSError:
            continue
        record[rel] = e["h"]
        written += 1
    if root.exists():
        for rel, path in list(_outbox_files(root)):
            if rel not in wanted:
                path.unlink(missing_ok=True)
        for dirpath, _dirs, _files in sorted(os.walk(root), key=lambda w: -len(w[0])):
            d = Path(dirpath)
            if d != root and d.relative_to(root).parts[0] not in OUTBOX_OWN and not any(d.iterdir()):
                d.rmdir()
    for rel in list(record):
        if rel not in wanted:
            record.pop(rel)
    return written


# ----------------------------------------------------------------- one data run
def _prune(cfg: Settings, state: dict, now: float) -> None:
    state["clashes"] = [c for c in state["clashes"] if now - c["when"] < CLASH_KEEP_DAYS * 86400]
    backups = cfg.sync_dir / "backup"
    if backups.exists():
        for day in backups.iterdir():
            try:
                age = now - datetime.strptime(day.name, "%Y-%m-%d").timestamp()
            except ValueError:
                continue
            if age > (BACKUP_DAYS + 1) * 86400:
                shutil.rmtree(day, ignore_errors=True)


def sync_data(cfg: Settings, state: dict, peer_note: dict | None, now: float, frozen_repos: set[str] = frozenset(),
              allow_deletes: bool = False, note_extra: dict | None = None) -> ImportResult:
    """Scan, import the other PC's newer versions, refresh this PC's outbox, then write the note (files first, then
    the note that names them) and the state."""
    scan(cfg, state, now, set(frozen_repos))
    res = import_from_peer(cfg, state, peer_note, set(frozen_repos), allow_deletes, now)
    res.skipped = [*state["errors"], *res.skipped]
    res.exported = refresh_outbox(cfg, state, peer_note)
    _prune(cfg, state, now)
    note = make_note(cfg, state, now, note_extra)
    if not _same_note(read_note(cfg, cfg.machine), note):  # the note is large: Syncthing sends it only on change
        write_note(cfg, note)
    _write_json(_alive_path(cfg, cfg.machine), {"written": now})
    save_state(cfg, state)
    return res
