"""MCP server exposing aiCoach workout tools."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import AliasChoices, BaseModel, Field, model_validator

from aicoach.config import Settings, load_settings
from aicoach.db import connect, init_db
from aicoach.progress import build_progress
from aicoach.repository import SetInput, WorkoutRepository

mcp = FastMCP("aiCoach")


class WorkoutSetInput(BaseModel):
    reps: int = Field(ge=1, description="Number of repetitions completed.")
    weight: float = Field(
        ge=0,
        description="Weight used for the set.",
        validation_alias=AliasChoices("weight", "weight_kg", "weight_lb"),
    )
    unit: str | None = Field(default=None, description="Weight unit, e.g. kg or lb.")
    rpe: float | None = Field(default=None, ge=1, le=10, description="Optional RPE rating.")
    note: str | None = Field(default=None, description="Optional note for this set.")

    @model_validator(mode="before")
    @classmethod
    def infer_unit_from_weight_alias(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if data.get("unit") is not None:
            return data
        if "weight_kg" in data and "weight" not in data:
            data = {**data, "unit": "kg"}
        elif "weight_lb" in data and "weight" not in data:
            data = {**data, "unit": "lb"}
        return data


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
def get_session(session_id: int) -> str:
    """Return one workout session with set ids for editing or deletion."""
    with _repository() as repo:
        result = repo.get_session(session_id)
    return json.dumps(result, indent=2)


@mcp.tool()
def update_session(
    session_id: int,
    performed_on: str | None = None,
    note: str | None = None,
) -> str:
    """Update a workout session date or session note."""
    with _repository() as repo:
        result = repo.update_session(session_id, performed_on=performed_on, note=note)
    return json.dumps(result, indent=2)


@mcp.tool()
def update_workout_set(
    set_id: int,
    reps: int | None = None,
    weight: float | None = None,
    unit: str | None = None,
    rpe: float | None = None,
    note: str | None = None,
) -> str:
    """Update one logged set by id."""
    with _repository() as repo:
        result = repo.update_workout_set(
            set_id,
            reps=reps,
            weight=weight,
            unit=unit,
            rpe=rpe,
            note=note,
        )
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_session(session_id: int) -> str:
    """Delete an entire workout session and all sets in it."""
    with _repository() as repo:
        result = repo.delete_session(session_id)
    return json.dumps(result, indent=2)


@mcp.tool()
def delete_exercise_from_session(session_id: int, exercise: str) -> str:
    """Delete one exercise and all of its sets from a workout session."""
    with _repository() as repo:
        result = repo.delete_exercise_from_session(session_id, exercise)
    return json.dumps(result, indent=2)


@mcp.tool()
def merge_sessions(target_session_id: int, source_session_ids: list[int]) -> str:
    """Merge one or more source sessions into a target session."""
    with _repository() as repo:
        result = repo.merge_sessions(target_session_id, source_session_ids)
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
