from enum import Enum
from typing import Literal, List, Optional
from pydantic import BaseModel, Field


class CalcRequest(BaseModel):
    weight_kg: float = Field(gt=0)
    height_cm: float = Field(gt=0)
    age: int = Field(gt=0)
    gender: Literal["male", "female"]
    activity_level: Literal["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]
    goal: Literal["lose", "maintain", "gain"]
    goal_rate_kg_per_week: float = Field(default=0.5, gt=0)


class CalcResponse(BaseModel):
    bmr_kcal: float
    tdee_kcal: float
    calorie_goal_kcal: float


class AgentRequest(BaseModel):
    message: str


class AgentResponse(BaseModel):
    response: str
    iterations_used: int


class MealParseRequest(BaseModel):
    meal_text: str
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] = "snack"


class MealItem(BaseModel):
    name: str
    quantity: float
    unit: str
    calories_kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    confidence: Literal["high", "medium", "low"] = "medium"


class MealParseResponse(BaseModel):
    items: List[MealItem]
    total_kcal: float
    meal_type: str
    model_latency_ms: float


class Intent(str, Enum):
    """ADR-005 contract 1. Not a second router — see agent_service.py's
    _run_agent_orchestrator docstring/comments. Exists solely to name the
    case where neither the profile shape nor meal_text applies (UNKNOWN);
    known-shape dispatch remains purely presence-based on ParsedRequest's
    other fields."""
    LOG_MEAL = "log_meal"
    SET_PROFILE = "set_profile"
    UNKNOWN = "unknown"


class ParsedRequest(BaseModel):
    """Structured fields extracted from a free-text /api/agent message.

    Produced by services/agent_service.py::extract_request_fields (ADR-003
    Action Item 5) — a single-shot structured-output LLM call, NOT a chat
    completion. Fields absent from the message come back as None, never a
    hallucinated default.

    - `profile`: populated only when the message contains ALL of
      CalcRequest's required fields (weight_kg, height_cm, age, gender,
      activity_level, goal). Otherwise None — the orchestrator does not run
      the calc pipeline on a partial profile.
    - `meal_text` / `meal_type`: populated when the message describes a meal
      to log. `meal_type` defaults to "snack" (matching MealParseRequest)
      when meal_text is present but no meal type was mentioned.
    - `intent`: ADR-005 contract 1/2 — classified in the same LLM call as
      the fields above. A soft signal for the future ReAct-fallback routing
      decision (ADR-005 Phase 2 sub-stage 2d), NOT read anywhere yet to
      decide which handler runs; that remains purely presence-based on
      `profile`/`meal_text`.
    """
    profile: Optional[CalcRequest] = None
    meal_text: Optional[str] = None
    meal_type: Optional[Literal["breakfast", "lunch", "dinner", "snack"]] = None
    intent: Intent
