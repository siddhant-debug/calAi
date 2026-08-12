"""Tests for services/calc_pipeline.py (ADR-003 Action Item 2).

Confirms the extraction produced no behavior change: run_calc_pipeline must
match calling calculate_bmr -> calculate_tdee -> calculate_calorie_goal
manually in sequence, and must propagate ValueError from the underlying
tools uncaught (the exception path /api/calculate depends on for its 422
response).
"""
import logging

import pytest

from calai_backend.schemas import CalcRequest
from calai_backend.services.calc_pipeline import run_calc_pipeline
from calai_backend.tools.bmr import calculate_bmr
from calai_backend.tools.calorie_goal import calculate_calorie_goal
from calai_backend.tools.tdee import calculate_tdee


PROFILES = [
    # male, losing weight
    dict(weight_kg=80, height_cm=180, age=28, gender="male",
         activity_level="moderately_active", goal="lose", goal_rate_kg_per_week=0.5),
    # female, maintaining
    dict(weight_kg=58, height_cm=162, age=34, gender="female",
         activity_level="lightly_active", goal="maintain", goal_rate_kg_per_week=0.5),
    # male, gaining, custom rate
    dict(weight_kg=65, height_cm=170, age=22, gender="male",
         activity_level="very_active", goal="gain", goal_rate_kg_per_week=0.25),
]


@pytest.mark.parametrize("profile_kwargs", PROFILES)
def test_run_calc_pipeline_matches_manual_sequence(profile_kwargs):
    profile = CalcRequest(**profile_kwargs)

    result = run_calc_pipeline(profile)

    expected_bmr = calculate_bmr(profile.weight_kg, profile.height_cm, profile.age, profile.gender)
    expected_tdee = calculate_tdee(expected_bmr, profile.activity_level)
    expected_goal = calculate_calorie_goal(expected_tdee, profile.goal, profile.goal_rate_kg_per_week)

    assert result.bmr_kcal == expected_bmr
    assert result.tdee_kcal == expected_tdee
    assert result.calorie_goal_kcal == expected_goal


def test_run_calc_pipeline_raises_valueerror_on_invalid_activity_level():
    # Pydantic's CalcRequest normally rejects this via Literal, but the
    # pipeline itself must still raise ValueError (not swallow it) if it
    # ever receives an invalid value — this is what /api/calculate's
    # try/except ValueError -> 422 depends on.
    profile = CalcRequest.model_construct(
        weight_kg=80.0, height_cm=180.0, age=28, gender="male",
        activity_level="hyperactive", goal="lose", goal_rate_kg_per_week=0.5,
    )
    with pytest.raises(ValueError, match="activity_level must be one of"):
        run_calc_pipeline(profile)


def test_run_calc_pipeline_raises_valueerror_on_invalid_gender():
    profile = CalcRequest.model_construct(
        weight_kg=80.0, height_cm=180.0, age=28, gender="nonbinary",
        activity_level="sedentary", goal="lose", goal_rate_kg_per_week=0.5,
    )
    with pytest.raises(ValueError, match="gender must be 'male' or 'female'"):
        run_calc_pipeline(profile)


def test_run_calc_pipeline_raises_valueerror_on_invalid_goal():
    profile = CalcRequest.model_construct(
        weight_kg=80.0, height_cm=180.0, age=28, gender="male",
        activity_level="sedentary", goal="bulk", goal_rate_kg_per_week=0.5,
    )
    with pytest.raises(ValueError, match="goal must be 'lose', 'maintain', or 'gain'"):
        run_calc_pipeline(profile)


# ---------------------------------------------------------------------------
# ADR-005 REQ-05/contract 6 — WARNING: computed TDEE outside [500, 6000] kcal/day
# ---------------------------------------------------------------------------

def test_run_calc_pipeline_logs_warning_for_tdee_below_sane_range(caplog):
    # weight/height near zero, age large -> BMR/TDEE well under 500 kcal.
    profile = CalcRequest(
        weight_kg=0.1, height_cm=0.1, age=1, gender="male",
        activity_level="sedentary", goal="maintain", goal_rate_kg_per_week=0.5,
    )
    caplog.set_level(logging.WARNING, logger="calai_backend.services.calc_pipeline")

    result = run_calc_pipeline(profile)

    assert result.tdee_kcal < 500
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "sane physiological range" in r.getMessage()
    ]
    assert len(warnings) == 1


def test_run_calc_pipeline_logs_warning_for_tdee_above_sane_range(caplog):
    # Large weight/height, extra_active multiplier -> TDEE well over 6000 kcal.
    profile = CalcRequest(
        weight_kg=1000, height_cm=300, age=1, gender="male",
        activity_level="extra_active", goal="maintain", goal_rate_kg_per_week=0.5,
    )
    caplog.set_level(logging.WARNING, logger="calai_backend.services.calc_pipeline")

    result = run_calc_pipeline(profile)

    assert result.tdee_kcal > 6000
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "sane physiological range" in r.getMessage()
    ]
    assert len(warnings) == 1


def test_run_calc_pipeline_no_warning_for_normal_in_range_tdee(caplog):
    profile = CalcRequest(
        weight_kg=80, height_cm=180, age=28, gender="male",
        activity_level="moderately_active", goal="lose", goal_rate_kg_per_week=0.5,
    )
    caplog.set_level(logging.WARNING, logger="calai_backend.services.calc_pipeline")

    result = run_calc_pipeline(profile)

    assert 500 <= result.tdee_kcal <= 6000
    warnings = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "sane physiological range" in r.getMessage()
    ]
    assert warnings == []
