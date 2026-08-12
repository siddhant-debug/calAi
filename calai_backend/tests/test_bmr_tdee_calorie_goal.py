"""Direct unit tests for the deterministic formula tools.

These had zero existing coverage before this suite. Pure functions, exact
input -> exact expected output, no LLM calls, no tolerance ranges (per
CLAUDE.md / ADR-004: deterministic tools belong in pytest, not evals).
"""
import pytest

from calai_backend.tools.bmr import calculate_bmr
from calai_backend.tools.calorie_goal import calculate_calorie_goal
from calai_backend.tools.tdee import calculate_tdee


# ---------------------------------------------------------------------------
# calculate_bmr — Mifflin-St Jeor
# ---------------------------------------------------------------------------

def test_bmr_male():
    # 10*70 + 6.25*175 - 5*30 + 5 = 700 + 1093.75 - 150 + 5 = 1648.75 -> 1648.8
    assert calculate_bmr(70, 175, 30, "male") == 1648.8


def test_bmr_female():
    # 10*60 + 6.25*165 - 5*25 - 161 = 1345.25 -> rounds to 1345.2
    assert calculate_bmr(60, 165, 25, "female") == 1345.2


def test_bmr_invalid_gender_raises():
    with pytest.raises(ValueError, match="gender must be 'male' or 'female'"):
        calculate_bmr(70, 175, 30, "other")


# ---------------------------------------------------------------------------
# calculate_tdee
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "activity_level,expected",
    [
        ("sedentary", 1800.0),
        ("lightly_active", 2062.5),
        ("moderately_active", 2325.0),
        ("very_active", 2587.5),
        ("extra_active", 2850.0),
    ],
)
def test_tdee_all_activity_levels(activity_level, expected):
    assert calculate_tdee(1500.0, activity_level) == expected


def test_tdee_invalid_activity_level_raises():
    with pytest.raises(ValueError, match="activity_level must be one of"):
        calculate_tdee(1500.0, "extremely_active")


# ---------------------------------------------------------------------------
# calculate_calorie_goal
# ---------------------------------------------------------------------------

def test_calorie_goal_maintain_ignores_rate():
    assert calculate_calorie_goal(2000.0, "maintain", goal_rate_kg_per_week=2.0) == 2000.0


def test_calorie_goal_lose_default_rate():
    # daily_delta = (0.5 * 7700) / 7 = 550.0
    assert calculate_calorie_goal(2000.0, "lose") == 1450.0


def test_calorie_goal_gain_custom_rate():
    # daily_delta = (0.25 * 7700) / 7 = 275.0
    assert calculate_calorie_goal(2000.0, "gain", goal_rate_kg_per_week=0.25) == 2275.0


def test_calorie_goal_invalid_goal_raises():
    with pytest.raises(ValueError, match="goal must be 'lose', 'maintain', or 'gain'"):
        calculate_calorie_goal(2000.0, "bulk")
