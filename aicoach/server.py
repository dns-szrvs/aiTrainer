"""MCP server exposing aiCoach workout tools."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from aicoach.config import Settings, load_settings
from aicoach.db import connect, init_db
from aicoach.progress import build_progress
from aicoach.repository import SetInput, WorkoutRepository

mcp = FastMCP("aiCoach")


class WorkoutSetInput(BaseModel):
    reps: int = Field(ge=1, description="Number of repetitions completed.")
    weight: float = Field(ge=0, description="Weight used for the set.")
    unit: str | None = Field(default=None, description="Weight unit, e.g. kg or lb.")
    rpe: float | None = Field(default=None, ge=1, le=10, description="Optional RPE rating.")
    note: str | None = Field(default=None, description="Optional note for this set.")


def _get_settings() -> Settings:
    return load_settings()


@contextmanager
def _repository():
    settings = _get_settings()
    conn = connect(settings.db_path)
    init_db(conn)
    repo = WorkoutRepository(
        conn,
        default_unit=settings.default_unit,
        idle_timeout_seconds=settings.idle_timeout_seconds,
    )
    try:
        yield repo
    finally:
        conn.close()


def _to_set_inputs(sets: list[WorkoutSetInput]) -> list[SetInput]:
    return [
        SetInput(
            reps=item.reps,
            weight=item.weight,
            unit=item.unit,
            rpe=item.rpe,
            note=item.note,
        )
        for item in sets
    ]


@mcp.tool()
def log_workout(
    exercise: str,
    sets: list[WorkoutSetInput],
    performed_on: str | None = None,
    note: str | None = None,
) -> str:
    """Log sets for one exercise and attach them to the current open workout session."""
    with _repository() as repo:
        result = repo.log_workout(
            exercise,
            _to_set_inputs(sets),
            performed_on=performed_on,
            note=note,
        )
    return json.dumps(result, indent=2)


@mcp.tool()
def get_current_workout() -> str:
    """Return the open workout session and all exercises logged so far today."""
    with _repository() as repo:
        result = repo.get_current_workout()
    if result is None:
        return json.dumps({"message": "No open workout session right now."}, indent=2)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_exercise_history(exercise: str, limit: int = 10) -> str:
    """Return recent workout sessions for a single exercise."""
    with _repository() as repo:
        result = repo.get_exercise_history(exercise, limit=limit)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_recent_workouts(limit: int = 10, days: int | None = None) -> str:
    """Return recent workout sessions across all exercises."""
    with _repository() as repo:
        result = repo.get_recent_workouts(limit=limit, days=days)
    return json.dumps(result, indent=2)


@mcp.tool()
def get_progress(exercise: str) -> str:
    """Return coaching signals such as estimated 1RM, volume trend, and PRs."""
    with _repository() as repo:
        result = build_progress(repo, exercise)
    return json.dumps(result, indent=2)


@mcp.tool()
def list_exercises() -> str:
    """List known exercises and aliases to help normalize exercise names."""
    with _repository() as repo:
        result = repo.list_exercises()
    return json.dumps(result, indent=2)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
