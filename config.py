"""Loads apps.yaml and tasks.yaml into typed config objects."""
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

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
    processes: list[ProcessConfig]


class TaskConfig(BaseModel):
    """A one-shot Start of Day job from tasks.yaml."""
    id: str
    label: str
    description: str = ""
    cwd: str
    cmd: list[str]
    expected_minutes: int | None = None
    # optional: a quick command (same cwd) whose output line says what today's run will do; shown before Start
    preview_cmd: list[str] | None = None
    env: dict[str, str] = Field(default_factory=dict)

    def resolved_cwd(self) -> Path:
        return (MARCO_DIR / self.cwd).resolve()

    def resolved_cmd(self) -> list[str]:
        return [_resolve(token) for token in self.cmd]

    def resolved_preview_cmd(self) -> list[str] | None:
        return [_resolve(token) for token in self.preview_cmd] if self.preview_cmd else None


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
