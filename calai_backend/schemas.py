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
    profile: CalcRequest | None = None
    """The client's currently-confirmed profile, if any — sent as context on every
    call so the backend can reference it (e.g. weekly_checkin's last_weight_kg,
    recommendation math) without a server-side lookup. None during onboarding,
    before any profile is confirmed."""
    trigger: Literal["message", "weekly_checkin"] = "message"
    """"message" (default): process `message` as free text, exactly today's behavior.
    "weekly_checkin": the client has locally determined a check-in is due and is
    explicitly requesting a weekly_checkin-typed AgentResponse; `message` is
    ignored server-side in this mode."""
    conversation_history: list[str] | None = None
    """Prior USER messages from the current onboarding session, oldest first,
    NOT including `message` itself (that stays in `message`, unchanged from
    today's contract). Populated by the client only while onboarding is
    in progress (before `profile` has been confirmed via `/api/calculate`
    + `storage_service.saveProfile`). None or empty on the first turn of a
    session, and on any call made after a profile is already confirmed
    (that path already sends `profile` instead — see ADR-007 Part 3).
    Agent-authored messages (questions the assistant asked) are NOT
    included — only what the user said, since those are the only messages
    that can carry extractable profile fields."""


class AgentMessageType(str, Enum):
    """Mirrors the Intent enum's (str, Enum) pattern. Discriminates which of
    AgentResponse's four optional payload fields, if any, is populated.
    Exactly one of {slot_fill, profile_confirmation, recommendation, weekly_checkin}
    is non-None when message_type != INFO; all four are None when message_type == INFO."""
    INFO = "info"
    SLOT_FILL_QUESTION = "slot_fill_question"
    PROFILE_CONFIRMATION = "profile_confirmation"
    RECOMMENDATION = "recommendation"
    WEEKLY_CHECKIN = "weekly_checkin"


class SlotFillPayload(BaseModel):
    missing: list[str]
    """Exact field-name list, reusing ADR-005's NeedsMoreInfo.missing naming and
    contents verbatim when the orchestrator/handler layer already computes it."""


class ProfileConfirmationPayload(BaseModel):
    profile: CalcRequest
    """The fully-extracted, not-yet-confirmed profile — same shape /api/calculate
    accepts, so 'Confirm' in the UI can POST this object to /api/calculate unchanged."""
    preview: CalcResponse
    """bmr_kcal/tdee_kcal/calorie_goal_kcal computed from `profile` via the same
    deterministic calc pipeline /api/calculate uses. Computing this preview does
    not persist or confirm the profile."""


class RecommendationPayload(BaseModel):
    calorie_goal_kcal: float
    tdee_kcal: float
    bmr_kcal: float
    rationale: str
    """Short human-readable reason for the recommendation. Always present."""


class WeeklyCheckinPayload(BaseModel):
    last_weight_kg: float | None = None
    """Most recent weight on record, if any. None on a client's very first check-in."""


class AgentResponse(BaseModel):
    response: str
    iterations_used: int
    message_type: AgentMessageType = AgentMessageType.INFO
    slot_fill: SlotFillPayload | None = None
    profile_confirmation: ProfileConfirmationPayload | None = None
    recommendation: RecommendationPayload | None = None
    weekly_checkin: WeeklyCheckinPayload | None = None


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
