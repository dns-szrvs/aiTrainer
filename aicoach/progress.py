"""Progress signals for coaching recommendations."""

from __future__ import annotations

from typing import Any, Literal

from aicoach.repository import WorkoutRepository

Trend = Literal["up", "flat", "down", "insufficient_data"]


def estimate_1rm_epley(weight: float, reps: int) -> float:
    if reps <= 0:
        raise ValueError("reps must be positive")
    if reps == 1:
        return weight
    return round(weight * (1 + reps / 30), 2)


def _volume_trend(volumes: list[float]) -> Trend:
    if len(volumes) < 2:
        return "insufficient_data"
    previous, current = volumes[-2], volumes[-1]
    if current > previous * 1.02:
        return "up"
    if current < previous * 0.98:
        return "down"
    return "flat"


def _sessions_since_weight_increase(weights: list[float]) -> int | None:
    if len(weights) < 2:
        return None
    last_increase_index = None
    for index in range(1, len(weights)):
        if weights[index] > weights[index - 1]:
            last_increase_index = index
    if last_increase_index is None:
        return len(weights) - 1
    return len(weights) - 1 - last_increase_index


def build_progress(repo: WorkoutRepository, exercise_name: str) -> dict[str, Any]:
    exercise = repo.resolve_exercise(exercise_name)
    summaries = repo.get_exercise_session_summaries(exercise.canonical_name)
    if not summaries:
        return {
            "exercise": exercise.canonical_name,
            "sessions_logged": 0,
            "message": "No history yet for this exercise.",
        }

    last = summaries[-1]
    personal_best = max(summaries, key=lambda item: item["top_weight"])
    estimated_1rm = estimate_1rm_epley(last["top_weight"], last["top_reps"])
    pb_1rm = estimate_1rm_epley(personal_best["top_weight"], personal_best["top_reps"])
    volumes = [item["volume"] for item in summaries]
    weights = [item["top_weight"] for item in summaries]

    return {
        "exercise": exercise.canonical_name,
        "sessions_logged": len(summaries),
        "last_session": {
            "performed_on": last["performed_on"],
            "top_weight": last["top_weight"],
            "top_reps": last["top_reps"],
            "volume": last["volume"],
            "estimated_1rm": estimated_1rm,
        },
        "personal_best": {
            "performed_on": personal_best["performed_on"],
            "top_weight": personal_best["top_weight"],
            "top_reps": personal_best["top_reps"],
            "estimated_1rm": pb_1rm,
        },
        "volume_trend": _volume_trend(volumes),
        "sessions_since_last_weight_increase": _sessions_since_weight_increase(weights),
        "recent_sessions": summaries[-5:],
    }
