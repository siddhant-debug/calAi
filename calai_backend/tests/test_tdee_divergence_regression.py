"""Regression test for the ReAct-loop TDEE divergence found in ADR-003 Action Item 7.

Bug context (see artefacts/NOTES-orchestrator-vs-react.md and
artefacts/adr003-latency-comparison.json): on the "profile_only" latency
comparison message ("I'm a 28 year old male, 75kg, 178cm tall, moderately
active, and I want to lose weight at 0.5kg per week."), the old ReAct
tool-calling loop's LLM reported a TDEE of 3726 kcal, while the deterministic
orchestrator path (calai_backend/services/calc_pipeline.py) computed 2678
kcal for the identical input. The 3726 value was never a case of the LLM
picking a wrong tool -- it silently re-derived (and got wrong) arithmetic
that a fixed BMR->TDEE formula should never depend on a language model for.

This divergence was found by accident, in an n=1 ad hoc latency script, and
had no permanent regression case guarding it until now. This test pins the
correct deterministic value so any future change to calc_pipeline.py (or the
tools it calls) that reintroduces LLM-derived or otherwise incorrect TDEE
arithmetic for this exact profile will fail loudly here instead of being
found by luck again.

Intended cross-reference: once ADR-005 (archdocs/ADR-005-router-handler-
registry.md) lands, its "Known Limitations" section should point back to
this test as the guard for the correctness gap ADR-003/ADR-005 identified in
the old ReAct loop.

NOTE: this test only exercises calc_pipeline.py's deterministic path. It
does not and cannot exercise the old ReAct loop's LLM-driven arithmetic
(that path is nondeterministic and calls a live model) -- the guarantee here
is "the deterministic path stays correct," not "the ReAct loop can never
regress," since the ReAct loop was never deterministic to begin with.
"""
import pytest

from calai_backend.schemas import CalcRequest
from calai_backend.services.calc_pipeline import run_calc_pipeline

# Exact profile fields extracted from the "profile_only" message in
# artefacts/adr003-latency-comparison.json:
#   "I'm a 28 year old male, 75kg, 178cm tall, moderately active, and I want
#   to lose weight at 0.5kg per week."
DIVERGENCE_PROFILE = dict(
    weight_kg=75,
    height_cm=178,
    age=28,
    gender="male",
    activity_level="moderately_active",
    goal="lose",
    goal_rate_kg_per_week=0.5,
)

# The old ReAct loop reported this TDEE for the profile above -- it must
# NEVER be reproduced by the deterministic pipeline.
BUGGY_REACT_LOOP_TDEE_KCAL = 3726

# The orchestrator's deterministic calc_pipeline.py TDEE for the same
# profile -- this is the value that must always come out.
CORRECT_TDEE_KCAL = 2678


def test_calc_pipeline_tdee_matches_orchestrator_not_react_loop_bug():
    profile = CalcRequest(**DIVERGENCE_PROFILE)

    result = run_calc_pipeline(profile)

    assert result.tdee_kcal == pytest.approx(CORRECT_TDEE_KCAL, abs=1.0), (
        f"Expected deterministic TDEE ~{CORRECT_TDEE_KCAL} kcal for the "
        f"profile_only divergence profile, got {result.tdee_kcal}."
    )
    assert result.tdee_kcal != pytest.approx(BUGGY_REACT_LOOP_TDEE_KCAL, abs=1.0), (
        "calc_pipeline.py reproduced the old ReAct loop's incorrect "
        f"LLM-derived TDEE ({BUGGY_REACT_LOOP_TDEE_KCAL} kcal) instead of "
        "the correct deterministic value -- this is the exact bug ADR-003 "
        "Action Item 7 found."
    )

