"""Where everything lives. Every path the tool touches comes from a Settings, so tests run the PCs in temp folders."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Every machine that may run the sync (three-machine design, 20 Nov 2026). A machine that has never written a note is
# not yet part of the sync: the others neither wait for it nor stage files for it (data_sync.joined_peers).
MACHINES = ("desktop", "laptop", "vps")
ALWAYS_ON = ("vps",)  # its sync runs every few minutes whatever it does: a recent sync says nothing about a daily run
FORGET_AFTER_DAYS = 30  # a PC whose note has been missing (or unreadable) this long is no longer waited for
DEFAULT_REPOS = (
    "Marco/Australia-Rates", "Marco/CB Pricer", "Marco/Curve", "Marco/FOMC", "Marco/launcher",
    "IBKR", "Trend", "FXMGT/JPMQFX01_build",
    # a worktree of Trend on feat/macro-v1 (Stephen, 28 Nov 2026: "add this C:\Users\User\Trend_v1 to tailscale sync",
    # "for all 3pcs"). It shares Trend's Git folder; each PC makes it once (git -C Trend worktree add ..\Trend_v1
    # feat/macro-v1) and until then shows it as "not on this PC". No daily task uses it; its only ignored files are a cache
    "Trend_v1",
)
LAUNCHER_REPO = "Marco/launcher"  # tasks.yaml and this tool: on the daily tasks' side of every rule
DEFAULT_PLAIN_ROOTS = {"FXMGT": ["JPMQFX01_build"]}  # folders that are not repos: all data, minus these sub-folders
OUTBOX_NAMES = {"laptop": "TripSync", "desktop": "DesktopSync", "vps": "VpsSync"}  # laptop: the trip sync's folder

INTERVAL_MIN = 5
RELAY_AFTER_H = 6  # a version another PC made is staged here too once that PC's sync has been quiet this long
STABLE_S = 60  # a file changed more recently than this is still being written: not exported or replaced
BRAKE_MIN, BRAKE_FRACTION = 50, 0.02  # more deletions than max(these) in one run are held
BRAKE_DAY_MIN, BRAKE_DAY_FRACTION = 150, 0.05  # ... and more than max(these) in one day (runs added up)
TOMBSTONE_DAYS = 30  # a deletion stays in the note at least this long, and until every other PC's note shows it ...
TOMBSTONE_MAX_DAYS = 90  # ... or this long, whichever comes first
BACKUP_DAYS = 60  # backups of clashes and deletions (MachineSync\backup\<date>)
CLAIM_KEEP_DAYS = 30
FREEZE_UNTIL_HOUR = 9  # the claim-holding PC's busy repos keep their code until 09:00 the day after the claim


def syncthing_folders(home: Path, localappdata: str | Path | None) -> tuple[Path, ...]:
    """Every folder this PC's Syncthing shares (from its config.xml: the desktop's home is TripSync_syncthing, the
    laptop's the default under %LOCALAPPDATA%). The sync never writes into one of these that is not its own outbox:
    such a folder has its own writer (the VPS for IBKR's settlements) and Syncthing delivers it directly."""
    import xml.etree.ElementTree as ET

    candidates = [Path(home) / "TripSync_syncthing" / "config.xml"]
    if localappdata:
        candidates.append(Path(localappdata) / "Syncthing" / "config.xml")
    found: set[Path] = set()
    for cfg in candidates:
        try:
            root = ET.parse(cfg).getroot()
        except (OSError, ET.ParseError):
            continue
        for folder in root.iter("folder"):
            raw = folder.get("path") or ""
            if raw.startswith("~"):
                raw = str(Path(home)) + raw[1:]
            if raw:
                found.add(Path(raw).resolve())
    return tuple(sorted(found))


@dataclass
class Settings:
    home: Path
    machine: str
    repos: tuple[str, ...] = DEFAULT_REPOS
    plain_roots: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_PLAIN_ROOTS))
    syncthing_folders: tuple[Path, ...] = ()  # this PC's own Syncthing folders (see syncthing_folders())

    def __post_init__(self) -> None:
        self.home = Path(self.home)
        if self.machine not in MACHINES:
            raise ValueError(f"machine must be one of {MACHINES}, not {self.machine!r}")

    @property
    def peers(self) -> tuple[str, ...]:
        """The other machines, in MACHINES order."""
        return tuple(m for m in MACHINES if m != self.machine)

    @property
    def sync_dir(self) -> Path:
        return self.home / "MachineSync"

    def outbox(self, machine: str) -> Path:
        return self.home / OUTBOX_NAMES[machine]

    @property
    def own_outbox(self) -> Path:
        return self.outbox(self.machine)

    def outboxes(self) -> tuple[Path, ...]:
        """Every machine's outbox as this PC sees it: its own (send-only) and the others' (receive-only)."""
        return tuple(self.outbox(m) for m in MACHINES)

    def note_path(self, machine: str) -> Path:
        return self.outbox(machine) / "_state" / f"{machine}.json"

    def repo_path(self, repo: str) -> Path:
        return self.home / repo

    @classmethod
    def real(cls, machine: str | None = None) -> Settings:
        """This PC: home from USERPROFILE, name from MachineSync\\machine.txt (written by install)."""
        home = Path(os.environ.get("USERPROFILE", r"C:\Users\User"))
        if machine is None:
            machine = (home / "MachineSync" / "machine.txt").read_text(encoding="utf-8").strip()
        return cls(home=home, machine=machine,
                   syncthing_folders=syncthing_folders(home, os.environ.get("LOCALAPPDATA")))
