"""Server input validation tests."""

from aicoach.server import WorkoutSetInput


def test_workout_set_accepts_weight_field():
    item = WorkoutSetInput.model_validate({"reps": 8, "weight": 30})
    assert item.weight == 30
    assert item.unit is None


def test_workout_set_accepts_weight_kg_alias():
    item = WorkoutSetInput.model_validate({"reps": 8, "weight_kg": 30})
    assert item.weight == 30
    assert item.unit == "kg"


def test_workout_set_accepts_weight_lb_alias():
    item = WorkoutSetInput.model_validate({"reps": 5, "weight_lb": 135})
    assert item.weight == 135
    assert item.unit == "lb"
