import time

from calai_backend.logging_config import get_logger
from calai_backend.schemas import CalcRequest, CalcResponse
from calai_backend.tools.bmr import calculate_bmr
from calai_backend.tools.calorie_goal import calculate_calorie_goal
from calai_backend.tools.tdee import calculate_tdee

log = get_logger(__name__)

# Sane physiological bounds for a computed TDEE. ADR-005: this is the exact
# signal that would have caught the ADR-003 TDEE divergence (ReAct loop's
# 3726 kcal vs. the deterministic 2678 kcal on identical input) immediately
# instead of by accident in an n=1 latency script — see
# calai_backend/tests/test_tdee_divergence_regression.py.
_TDEE_MIN_SANE_KCAL = 500
_TDEE_MAX_SANE_KCAL = 6000

# Existing schemas already model exactly what this pipeline needs — no new
# Pydantic types required (per ADR-003 Action Item 2).
UserProfile = CalcRequest
CalcResult = CalcResponse


def run_calc_pipeline(profile: UserProfile) -> CalcResult:
    """Run BMR -> TDEE -> calorie goal sequentially. Deterministic, no LLM.

    Extracted from calai_backend/api/routes.py's /api/calculate handler,
    which previously called the three tools inline. Behavior and logging
    are unchanged, just relocated here (ADR-003 Action Item 2).
    """
    t0 = time.perf_counter()
    bmr = calculate_bmr(profile.weight_kg, profile.height_cm, profile.age, profile.gender)
    log.info("[Tool: calculate_bmr]         BMR = %.1f kcal  (%.1fms)", bmr, (time.perf_counter() - t0) * 1000)

    t0 = time.perf_counter()
    tdee = calculate_tdee(bmr, profile.activity_level)
    log.info("[Tool: calculate_tdee]        TDEE = %.1f kcal  (%.1fms)", tdee, (time.perf_counter() - t0) * 1000)
    if tdee < _TDEE_MIN_SANE_KCAL or tdee > _TDEE_MAX_SANE_KCAL:
        log.warning(
            "computed TDEE outside a sane physiological range (<%d or >%d kcal/day): "
            "tdee_kcal=%.1f weight_kg=%s height_cm=%s age=%s gender=%s activity_level=%s",
            _TDEE_MIN_SANE_KCAL, _TDEE_MAX_SANE_KCAL, tdee,
            profile.weight_kg, profile.height_cm, profile.age, profile.gender, profile.activity_level,
        )

    t0 = time.perf_counter()
    goal_kcal = calculate_calorie_goal(tdee, profile.goal, profile.goal_rate_kg_per_week)
    log.info(
        "[Tool: calculate_calorie_goal] Goal = %.1f kcal  goal=%s  rate=%.2f kg/wk  (%.1fms)",
        goal_kcal, profile.goal, profile.goal_rate_kg_per_week, (time.perf_counter() - t0) * 1000,
    )

    return CalcResult(bmr_kcal=bmr, tdee_kcal=tdee, calorie_goal_kcal=goal_kcal)
