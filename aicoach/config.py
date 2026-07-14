"""Configuration for aiCoach."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _default_db_path() -> Path:
    override = os.environ.get("AICOACH_DB_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "aicoach" / "aicoach.db"


@dataclass(frozen=True)
class Settings:
    db_path: Path
    default_unit: str
    idle_timeout_seconds: int


def load_settings() -> Settings:
    return Settings(
        db_path=_default_db_path(),
        default_unit=os.environ.get("AICOACH_DEFAULT_UNIT", "kg"),
        idle_timeout_seconds=int(os.environ.get("AICOACH_IDLE_TIMEOUT_SECONDS", "10800")),
    )
