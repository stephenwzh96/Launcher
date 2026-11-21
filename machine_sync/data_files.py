"""What counts as data: Git-ignored, non-secret files under the repos, plus the plain (non-repo) folders. Same rules
as the trip sync, plus: PostgreSQL data folders, SQLite side files, lock files, Syncthing conflict copies, and files
still being written (`.staging` folders, `.tmp`/`.partial`/`.part` files and folders)."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from .gitops import git
from .settings import Settings

SKIP_DIRS = {".git", ".venv", "venv", "env", "ENV", ".venv-ib", "node_modules", "__pycache__", ".pytest_cache",
             ".ruff_cache", ".mypy_cache", ".cache", ".vite", ".claude", ".workbuddy-ai", "logs", "htmlcov",
             ".streamlit", ".idea", ".vscode", ".superpowers", ".stversions", ".stfolder",
             ".staging", ".prev"}
# .staging: where a job writes before it swaps the result in (Trend's live-update). .prev: the copies one Start of Day
# build keeps of the raw files it replaces until it releases them (Trend data/sources/http.py); the next build on the
# same PC recovers or deletes them, and on another PC one would only be put back over a missing file
# files (and folders) a job is still writing: half a file must never reach the other PC
TEMP_SUFFIX = (".tmp", ".partial", ".part")
SKIP_FILE = re.compile(r"""(?ix)^(
    \.env(\..*)? | .*\.env | token\.json | credentials.*\.json | secrets?\.toml | .*\.(pem|key|pfx|p12)
  | .*\.log | .*\.py[cod] | \.coverage | nul | thumbs\.db | \.ds_store | .*\.tsync-tmp | .*\.msync-tmp | ~syncthing~.*
  | .*\.lock | .*-wal | .*-shm | .*-journal | .*\.sync-conflict-.* | \.stignore | .*\.(tmp|partial|part)
)$""")


def _skipped_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.endswith(".egg-info") or name.lower().endswith(TEMP_SUFFIX)
SKIP_SUFFIX = ("config/local.yaml",)
SQLITE_HEADER = b"SQLite format 3\x00"
# The one kind of file in a logs folder that is data: Trend's Start of Day record of a day (`data/logs/sod_<t>.json`),
# which IBKR's execution dashboard and the launcher's reminder read on whichever PC is in use. Progress files, locks,
# fetch status and logs stay on their PC.
LOG_RECORDS = re.compile(r"(^|/)data/logs/sod_\d{4}-\d{2}-\d{2}\.json$")


def skipped(rel: str) -> bool:
    norm = rel.replace("\\", "/")
    if LOG_RECORDS.search(norm):
        return False
    parts = norm.split("/")
    if any(p == ".." or _skipped_dir(p) for p in parts[:-1]):
        return True
    return bool(SKIP_FILE.match(parts[-1])) or norm.lower().endswith(SKIP_SUFFIX)


def _walk(root: Path, base: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        if "PG_VERSION" in filenames:  # a PostgreSQL data folder: live database files are never copied
            dirnames[:] = []
            continue
        # logs folders are walked only for their Start of Day records (skipped() drops everything else in them)
        dirnames[:] = [d for d in dirnames if d == "logs" or not _skipped_dir(d)]
        for name in filenames:
            rel = (Path(dirpath) / name).relative_to(base).as_posix()
            if not skipped(rel):
                yield rel


def _in_pg_folder(path: Path, stop: Path) -> bool:
    for parent in path.parents:
        if parent == stop:
            return False
        if (parent / "PG_VERSION").exists():
            return True
    return False


def data_files(cfg: Settings) -> dict[str, Path]:
    """Relative POSIX path (from home) -> absolute path, for every data file on this PC."""
    found: dict[str, Path] = {}
    for repo in cfg.repos:
        root = cfg.repo_path(repo)
        if not (root / ".git").exists():
            continue
        tracked = set(git(root, "ls-files", "-z").stdout.split("\0"))
        listing = git(root, "ls-files", "-z", "-o", "-i", "--exclude-standard", "--directory").stdout
        for entry in filter(None, listing.split("\0")):
            if entry.endswith("/"):
                name = entry.rstrip("/").split("/")[-1]
                if _skipped_dir(name) and name != "logs":  # a logs folder is walked for its Start of Day records only
                    continue
                rels = _walk(root / entry, root)
            else:
                rels = [entry] if not skipped(entry) and not _in_pg_folder(root / entry, root) else []
            for rel in rels:
                if rel not in tracked:
                    found[f"{repo}/{rel}"] = root / rel
    for top, exclude in cfg.plain_roots.items():
        root = cfg.home / top
        if root.exists():
            for rel in _walk(root, cfg.home):
                if not any(rel.startswith(f"{top}/{x}/") for x in exclude):
                    found[rel] = cfg.home / rel
    return found


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(16) == SQLITE_HEADER
    except OSError:
        return False


def sqlite_open(path: Path) -> bool:
    """An SQLite database with a -wal or -journal beside it is open (or was left mid-write): never move it."""
    return Path(f"{path}-wal").exists() or Path(f"{path}-journal").exists()
