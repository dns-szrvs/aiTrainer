"""Repository mutation tests."""

from __future__ import annotations

from datetime import timedelta

from aicoach.repository import SetInput


def _session_id(repo, fixed_now) -> int:
    result = repo.log_workout("bench press", [SetInput(reps=8, weight=60)], now=fixed_now)
    return result["session"]["id"]


def test_get_session_includes_set_ids(repo, fixed_now):
    session_id = _session_id(repo, fixed_now)
    session = repo.get_session(session_id)
    assert session["exercises"][0]["sets"][0]["id"] is not None


def test_update_session_changes_date(repo, fixed_now):
    session_id = _session_id(repo, fixed_now)
    updated = repo.update_session(session_id, performed_on="2026-07-10")
    assert updated["performed_on"] == "2026-07-10"
    assert updated["started_at"].startswith("2026-07-10")


def test_update_workout_set_changes_weight(repo, fixed_now):
    logged = repo.log_workout("squat", [SetInput(reps=5, weight=100)], now=fixed_now)
    set_id = logged["sets"][0]["id"]
    updated = repo.update_workout_set(set_id, weight=105, reps=4)
    assert updated["weight"] == 105
    assert updated["reps"] == 4


def test_delete_exercise_from_session_keeps_other_exercises(repo, fixed_now):
    session_id = _session_id(repo, fixed_now)
    repo.log_workout("squat", [SetInput(reps=5, weight=100)], now=fixed_now + timedelta(minutes=10))

    result = repo.delete_exercise_from_session(session_id, "bench press")
    assert result["removed_set_count"] == 1
    assert result["session_deleted"] is False
    assert len(result["session"]["exercises"]) == 1
    assert result["session"]["exercises"][0]["exercise"] == "Squat"


def test_delete_exercise_from_session_removes_empty_session(repo, fixed_now):
    session_id = _session_id(repo, fixed_now)
    result = repo.delete_exercise_from_session(session_id, "bench")
    assert result["session_deleted"] is True


def test_delete_session_removes_all_data(repo, fixed_now):
    session_id = _session_id(repo, fixed_now)
    repo.log_workout("squat", [SetInput(reps=5, weight=100)], now=fixed_now + timedelta(minutes=10))

    result = repo.delete_session(session_id)
    assert result["deleted"] is True
    assert result["removed_set_count"] == 2

    try:
        repo.get_session(session_id)
    except ValueError as exc:
        assert "not found" in str(exc)
    else:
        raise AssertionError("Expected deleted session to be missing")
