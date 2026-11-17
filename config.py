"""Loads apps.yaml and tasks.yaml into typed config objects."""
from datetime import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

MARCO_DIR = Path(__file__).resolve().parent.parent


def _resolve(token: str) -> str:
    if "/" in token or "\\" in token:
        return str((MARCO_DIR / token).resolve())
    return token


class ProcessConfig(BaseModel):
    cwd: str
    cmd: list[str]
    port: int
    log: str
    health: Literal["tcp", "http"] = "tcp"
    health_path: str = "/"
    env: dict[str, str] = Field(default_factory=dict)

    def resolved_cwd(self) -> Path:
        return (MARCO_DIR / self.cwd).resolve()

    def resolved_cmd(self) -> list[str]:
        return [_resolve(token) for token in self.cmd]


class AppConfig(BaseModel):
    id: str
    label: str
    open_port: int
    group: str = ""  # the page lists dashboards under their group, in the order the groups first appear
    processes: list[ProcessConfig]


class RemindConfig(BaseModel):
    """A banner on weekdays when a task has not been started by these times (tasks.yaml `remind`). Only a banner
    while the launcher is open: the task itself is still started by hand (Trend DECISIONS 2026-10-27)."""
    at: list[str]  # "HH:MM" in the task's timezone: the banner shows from the first; Dismiss hides it until the next
    # the file a run for decision date t leaves (relative to Marco/), with {t} for t as YYYY-MM-DD; t is the weekday
    # before today in the task's timezone (Monday's is Friday). No banner once it exists.
    record: str

    @field_validator("at")
    @classmethod
    def _clock_times(cls, at: list[str]) -> list[str]:
        for text in at:
            time.fromisoformat(text)  # ValueError: not HH:MM
        return at


class TaskConfig(BaseModel):
    """A one-shot Start of Day job from tasks.yaml."""
    id: str
    label: str
    description: str = ""
    summary: str = ""  # one line for the page; the description is shown on request
    when: str = ""  # when in the day it runs, as the page's time column shows it ("from 09:30")
    cwd: str
    cmd: list[str]
    expected_minutes: int | None = None
    # optional: a quick command (same cwd) whose output line says what today's run will do; shown before Start
    preview_cmd: list[str] | None = None
    # optional: a JSON file the task keeps current while it runs (schema sod_progress/1, progress.py); relative to
    # Marco/ like cwd, or absolute
    progress_file: str | None = None
    timezone: str | None = None  # the clock of the task's times (ETA, deliver-by, reminders); default this machine's
    remind: RemindConfig | None = None
    # optional: tasks sharing a claim name run on one PC per day; the launcher claims the day on GitHub before the
    # first of them starts (machine_sync/claims.py) and refuses on the other PC
    claim: str | None = None
    env: dict[str, str] = Field(default_factory=dict)

    def resolved_cwd(self) -> Path:
        return (MARCO_DIR / self.cwd).resolve()

    def resolved_cmd(self) -> list[str]:
        return [_resolve(token) for token in self.cmd]

    def resolved_preview_cmd(self) -> list[str] | None:
        return [_resolve(token) for token in self.preview_cmd] if self.preview_cmd else None

    def resolved_progress_file(self) -> Path | None:
        return (MARCO_DIR / self.progress_file).resolve() if self.progress_file else None

    def resolved_record(self, t: str) -> Path | None:
        """The record a run for decision date t (YYYY-MM-DD) leaves, from `remind`."""
        return (MARCO_DIR / self.remind.record.format(t=t)).resolve() if self.remind else None


def load_apps(path: Path) -> list[AppConfig]:
    raw = yaml.safe_load(path.read_text())
    return [AppConfig(**item) for item in raw]


def load_tasks(path: Path) -> list[TaskConfig]:
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text()) or []
    return [TaskConfig(**item) for item in raw]


def check_paths(apps: list[AppConfig], tasks: list[TaskConfig] = ()) -> list[str]:
    """Non-fatal sanity check: flags cwds/executables that don't exist yet
    (e.g. a venv deleted or a folder renamed by an update to that app)."""
    warnings = []
    for a in [*apps, *tasks]:
        for p in getattr(a, "processes", [a]):  # a task is its own single process
            cwd = p.resolved_cwd()
            if not cwd.exists():
                warnings.append(f"[{a.id}] cwd not found: {cwd}")
            first = p.cmd[0]
            if ("/" in first or "\\" in first):
                exe = _resolve(first)
                if not Path(exe).exists():
                    warnings.append(f"[{a.id}] executable not found: {exe}")
    return warnings
