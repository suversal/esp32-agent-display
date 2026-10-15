from __future__ import annotations

import os
import secrets
import tempfile
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 8787
    token: str = ""
    reorder_window_ms: int = 300
    permission_confirm_seconds: int = 10
    session_tombstone_minutes: int = 30
    hung_minutes: int = 15
    running_stale_minutes: int = 60
    waiting_stale_minutes: int = 120
    waiting_drop_hours: int = 12
    done_retention_minutes: int = 60
    idle_stale_minutes: int = 30
    restore_max_age_minutes: int = 120
    done_alert_min_seconds: int = 0
    quiet_hours: str = "23:00-08:00"
    show_command_text: bool = False
    vibe_island_path: str = "~/Library/Application Support/vibe-island/session-terminals.json"
    log_level: str = "info"
    max_sessions: int = 128
    project_alias: dict[str, str] = field(default_factory=dict)
    state_path: str = "~/.local/state/agent-display/state.json"
    log_path: str = "~/Library/Logs/agent-display/bridge.log"

    def validate(self) -> None:
        if not 0 <= self.port <= 65535:
            raise ValueError("port must be between 0 and 65535")
        if len(self.token) < 24:
            raise ValueError("token must have at least 24 characters")
        for name in (
            "reorder_window_ms", "permission_confirm_seconds",
            "session_tombstone_minutes", "hung_minutes", "running_stale_minutes",
            "waiting_stale_minutes", "waiting_drop_hours", "done_retention_minutes",
            "idle_stale_minutes", "restore_max_age_minutes", "done_alert_min_seconds",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative")
        if not 1 <= self.max_sessions <= 1024:
            raise ValueError("max_sessions must be between 1 and 1024")
        if self.quiet_hours:
            try:
                start, end = self.quiet_hours.split("-")
                for value in (start, end):
                    hour, minute = map(int, value.split(":"))
                    if not (0 <= hour < 24 and 0 <= minute < 60):
                        raise ValueError
            except ValueError:
                raise ValueError("quiet_hours must be HH:MM-HH:MM or empty") from None


def load_config(path: Path) -> Config:
    if not path.exists():
        token = secrets.token_urlsafe(32)
        atomic_write(path, f'port = 8787\ntoken = "{token}"\n')
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    allowed = {item.name for item in fields(Config)}
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown config fields: {', '.join(sorted(unknown))}")
    config = Config(**raw)
    config.validate()
    return config
