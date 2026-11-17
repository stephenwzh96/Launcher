"""Where everything lives. Every path the tool touches comes from a Settings, so tests run two PCs in temp folders."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

MACHINES = ("desktop", "laptop")
DEFAULT_REPOS = (
    "Marco/Australia-Rates", "Marco/CB Pricer", "Marco/Curve", "Marco/FOMC", "Marco/launcher",
    "IBKR", "Trend", "FXMGT/JPMQFX01_build",
)
DEFAULT_PLAIN_ROOTS = {"FXMGT": ["JPMQFX01_build"]}  # folders that are not repos: all data, minus these sub-folders
OUTBOX_NAMES = {"laptop": "TripSync", "desktop": "DesktopSync"}  # the laptop's keeps the trip sync's folder

INTERVAL_MIN = 5
STABLE_S = 60  # a file changed more recently than this is still being written: not exported or replaced
BRAKE_MIN, BRAKE_FRACTION = 50, 0.02  # more deletions than max(these) in one run are held
TOMBSTONE_DAYS = 30
BACKUP_DAYS = 14
CLAIM_KEEP_DAYS = 30
FREEZE_UNTIL_HOUR = 9  # the claim-holding PC's busy repos keep their code until 09:00 the day after the claim


@dataclass
class Settings:
    home: Path
    machine: str
    repos: tuple[str, ...] = DEFAULT_REPOS
    plain_roots: dict[str, list[str]] = field(default_factory=lambda: dict(DEFAULT_PLAIN_ROOTS))

    def __post_init__(self) -> None:
        self.home = Path(self.home)
        if self.machine not in MACHINES:
            raise ValueError(f"machine must be one of {MACHINES}, not {self.machine!r}")

    @property
    def peer(self) -> str:
        return "laptop" if self.machine == "desktop" else "desktop"

    @property
    def sync_dir(self) -> Path:
        return self.home / "MachineSync"

    def outbox(self, machine: str) -> Path:
        return self.home / OUTBOX_NAMES[machine]

    @property
    def own_outbox(self) -> Path:
        return self.outbox(self.machine)

    @property
    def peer_outbox(self) -> Path:
        return self.outbox(self.peer)

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
        return cls(home=home, machine=machine)
