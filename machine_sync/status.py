"""What Stephen sees: MachineSync\\sync_status.txt (rewritten every run) and sync.log (changes only)."""
from __future__ import annotations

import json
from datetime import datetime

from .code_sync import RepoResult
from .data_sync import ImportResult
from .settings import Settings

PEER_QUIET_MIN = 30
LOG_MAX_BYTES = 2_000_000


def _clash_line(c: dict, where: str) -> str:
    backup = f"; {where}'s copy kept at {c['backup']}" if c.get("backup") else ""
    return f"  changed on two PCs: {c['path']} ({c['kept']}'s version kept{backup})"


def _peer_line(machine: str, note: dict | None, seen_at: float | None, now: datetime, joined: bool) -> str:
    if note:
        seen = datetime.fromtimestamp(max(seen_at or 0, note.get("written", 0)))
        age = (now - seen).total_seconds() / 60
        quiet = f", {age / 60:.1f} h ago: off or offline?" if age > PEER_QUIET_MIN else ""
        return f"{machine} last ran {seen:%d %b %H:%M}{quiet}"
    if joined:
        return f"no note from {machine} now: is Syncthing connected?"
    return f"{machine} not in the sync yet"


def render(cfg: Settings, now: datetime, results: list[RepoResult], res: ImportResult, state: dict,
           peer_notes: dict[str, dict | None] | None, warnings: list[str], claims: list[dict],
           peer_seen: dict[str, float | None] | None = None) -> str:
    """peer_notes: every other PC's note (None: none, or not readable); peer_seen: each one's last heartbeat."""
    notes = {m: (peer_notes or {}).get(m) for m in cfg.peers}
    joined = set(state.get("peers_seen") or [])
    if not joined and not any(notes.values()):
        others = " or ".join(cfg.peers)
        head_tail = f" (no note from the {others} yet: is the sync installed there and Syncthing connected?)"
    else:
        head_tail = " (" + "; ".join(_peer_line(m, notes[m], (peer_seen or {}).get(m), now, m in joined)
                                     for m in cfg.peers) + ")"
    head = f"Sync status on {cfg.machine}, {now:%d %b %H:%M}{head_tail}"
    lines = [head]
    today = [c for c in claims if c["day"] == now.strftime("%Y-%m-%d")]
    lines.append("Today's daily run: " + (", ".join(
        f"claimed by {c['holder']}" + (f" at {c['at'][11:16]}" if len(c.get("at") or "") >= 16 else "")
        for c in today) if today else "not claimed yet"))
    lines.append("Code")
    width = max((len(r.repo) for r in results), default=0)
    lines += [f"  {r.repo:<{width}}  {r.line}" for r in results]
    lines.append("Data")
    live = sum(1 for e in state["files"].values() if not e["del"])
    acts = [f"{word} {n}" for word, n in (("took", res.taken), ("deleted", res.deleted), ("sent", res.exported),
                                         ("waiting for", res.waiting)) if n]
    lines.append(f"  {live:,} data files; " + ("this run: " + ", ".join(acts) if acts else "nothing to move"))
    source = " and ".join(res.held_from) or "the other PCs"
    if res.held_deletes and res.held_today is not None:
        lines.append(f"  {res.held_deletes} deletions from {source} held back: with the {res.held_today} already "
                     f"taken today they pass the day's limit of {res.day_limit}: check them, then run the sync with "
                     "--allow-deletes")
    elif res.held_deletes:
        lines.append(f"  {res.held_deletes} deletions from {source} held back (more than usual): check them, then run "
                     "the sync with --allow-deletes")
    day_ago = now.timestamp() - 86400
    lines += [_clash_line(c, cfg.machine) for c in state["clashes"] if c["when"] > day_ago]
    for machine, note in notes.items():
        lines += [_clash_line(c, machine) for c in (note or {}).get("clashes", []) if c.get("when", 0) > day_ago]
    lines += [f"  not taken: {s}" for s in res.skipped[:5]]
    if len(res.skipped) > 5:
        lines.append(f"  not taken: {len(res.skipped) - 5} more")
    unique = list(dict.fromkeys(warnings))
    if unique:
        lines.append("Warnings")
        lines += [f"  {w}" for w in unique]
    return "\n".join(lines) + "\n"


def write_status(cfg: Settings, now: datetime, text: str) -> None:
    """Rewrite sync_status.txt; append to sync.log the lines that are new since the last run (no repeats)."""
    cfg.sync_dir.mkdir(parents=True, exist_ok=True)
    (cfg.sync_dir / "sync_status.txt").write_text(text, encoding="utf-8")
    body = [ln.strip() for ln in text.splitlines()[1:] if ln.startswith("  ")]
    seen_path = cfg.sync_dir / "last_lines.json"
    try:
        seen = set(json.loads(seen_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    new = [ln for ln in body if ln not in seen and "nothing to move" not in ln]
    seen_path.write_text(json.dumps(body), encoding="utf-8")
    if new:
        log(cfg, now, new)


def log(cfg: Settings, now: datetime, lines: list[str]) -> None:
    path = cfg.sync_dir / "sync.log"
    with path.open("a", encoding="utf-8") as f:
        f.writelines(f"{now:%Y-%m-%d %H:%M:%S} {ln}\n" for ln in lines)
    if path.stat().st_size > LOG_MAX_BYTES:
        keep = path.read_text(encoding="utf-8", errors="replace").splitlines()[-5000:]
        path.write_text("\n".join(keep) + "\n", encoding="utf-8")
