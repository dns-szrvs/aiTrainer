"""Progress signal tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from aicoach.progress import build_progress, estimate_1rm_epley
from aicoach.repository import SetInput


def test_estimate_1rm_epley():
    assert estimate_1rm_epley(100, 1) == 100
    assert estimate_1rm_epley(100, 5) == 116.67


def test_build_progress_with_history(repo, fixed_now):
    repo.log_workout("bench press", [SetInput(reps=8, weight=60)], now=fixed_now)
    repo.log_workout(
        "bench press",
        [SetInput(reps=8, weight=62.5)],
        now=fixed_now + timedelta(days=3),
    )
    repo.log_workout(
        "bench press",
        [SetInput(reps=8, weight=65)],
        now=fixed_now + timedelta(days=6),
    )

    progress = build_progress(repo, "bench")
    assert progress["sessions_logged"] == 3
    assert progress["personal_best"]["top_weight"] == 65
    assert progress["volume_trend"] == "up"
    assert progress["sessions_since_last_weight_increase"] == 0


def test_build_progress_without_history(repo):
    progress = build_progress(repo, "curl")
    assert progress["sessions_logged"] == 0
    assert "No history yet" in progress["message"]
