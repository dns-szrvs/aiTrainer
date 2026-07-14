"""Repository and session grouping tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from aicoach.repository import SetInput


def test_resolve_exercise_creates_and_aliases(repo):
    exercise = repo.resolve_exercise("bench press")
    assert exercise.created is True
    assert exercise.canonical_name == "Bench Press"

    alias_match = repo.resolve_exercise("bench press")
    assert alias_match.created is False
    assert alias_match.id == exercise.id


def test_log_workout_groups_exercises_into_one_session(repo, fixed_now):
    repo.log_workout(
        "bench press",
        [SetInput(reps=8, weight=60), SetInput(reps=8, weight=60)],
        now=fixed_now,
    )
    repo.log_workout(
        "squat",
        [SetInput(reps=5, weight=100)],
        now=fixed_now + timedelta(minutes=20),
    )

    current = repo.get_current_workout(now=fixed_now + timedelta(minutes=20))
    assert current is not None
    assert len(current["exercises"]) == 2
    assert current["exercises"][0]["exercise"] == "Bench Press"
    assert current["exercises"][1]["exercise"] == "Squat"


def test_idle_timeout_opens_new_session(repo, fixed_now):
    repo.log_workout("bench press", [SetInput(reps=8, weight=60)], now=fixed_now)
    later = fixed_now + timedelta(hours=4)
    repo.log_workout("squat", [SetInput(reps=5, weight=100)], now=later)

    recent = repo.get_recent_workouts(limit=5)
    assert len(recent) == 2
    assert recent[0]["exercise_count"] == 1
    assert recent[1]["exercise_count"] == 1


def test_get_exercise_history_groups_sets_by_session(repo, fixed_now):
    repo.log_workout("deadlift", [SetInput(reps=5, weight=120)], now=fixed_now)
    repo.log_workout(
        "deadlift",
        [SetInput(reps=5, weight=125)],
        now=fixed_now + timedelta(days=2),
    )

    history = repo.get_exercise_history("deadlift", limit=5)
    assert history["exercise"] == "Deadlift"
    assert len(history["sessions"]) == 2
    assert history["sessions"][0]["sets"][0]["weight"] == 125


def test_list_exercises_includes_aliases(repo):
    repo.resolve_exercise("overhead press")
    exercises = repo.list_exercises()
    assert len(exercises) == 1
    assert "overhead press" in exercises[0]["aliases"]
