import time

import httpx
from fastapi import HTTPException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from calai_backend.config import MAX_STEPS, USE_ORCHESTRATOR
from calai_backend.logging_config import bind_correlation_id, get_logger
from calai_backend.prompts.calai_prompt import SYSTEM_PROMPT
from calai_backend.providers.llm import get_json_llm, get_llm
from calai_backend.schemas import (
    AgentMessageType,
    AgentResponse,
    CalcRequest,
    CalcResponse,
    Intent,
    ParsedRequest,
    ProfileConfirmationPayload,
    RecommendationPayload,
    SlotFillPayload,
    WeeklyCheckinPayload,
)
from calai_backend.services.calc_pipeline import run_calc_pipeline
from calai_backend.services.llm_call import llm_call
from calai_backend.services.meal_parse_agent import parse_meal
from calai_backend.tools.registry import get_dict, get_tools

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# extract_request_fields — ADR-003 Action Item 5
#
# Single-shot structured-output LLM call: free text -> ParsedRequest. This is
# NOT a chat completion — it's a JSON-mode extraction call, validated the
# same way services/meal_parse_agent.py::parse_meal validates its output
# (parse, raise ValueError on malformed JSON, no silent corruption).
# ---------------------------------------------------------------------------

_PROFILE_FIELD_NAMES = (
    "weight_kg", "height_cm", "age", "gender", "activity_level", "goal", "goal_rate_kg_per_week",
)

# goal_rate_kg_per_week has a schema default (CalcRequest) -- it is never a
# "missing" field for slot-filling purposes, matching the required_present
# check below.
_REQUIRED_PROFILE_FIELD_NAMES = tuple(f for f in _PROFILE_FIELD_NAMES if f != "goal_rate_kg_per_week")


class _ParsedRequestWithMissing(ParsedRequest):
    """ADR-007 Action Item 4/5 support, `agent_service.py`-local only (not in
    schemas.py -- ADR-005's NeedsMoreInfo.missing does not concretely exist
    yet, see SlotFillPayload's docstring). Subclasses ParsedRequest so every
    existing `isinstance(parsed, ParsedRequest)` check and attribute access
    (`.profile`, `.meal_text`, `.meal_type`, `.intent`) keeps working
    unchanged; this only adds one extra field carrying the same
    profile-field-presence information extract_request_fields already
    computes internally, so the orchestrator can build a precise
    SlotFillPayload.missing list without a second LLM call or reimplementing
    the presence check.
    """
    missing_profile_fields: list[str] = Field(default_factory=list)

EXTRACTION_PROMPT = """You are a structured data extractor for a calorie-tracking app.

Conversation so far (oldest first). This may be a single message or several turns of an
onboarding conversation.

{conversation}

There are TWO SEPARATE extraction instructions below — follow them independently, do not
blend them:

1. PROFILE FIELDS (weight_kg, height_cm, age, gender, activity_level, goal,
   goal_rate_kg_per_week): extract these from ALL messages in the conversation above,
   combined. A field mentioned in an earlier message and never contradicted later is still
   present — do not forget it just because it wasn't repeated in the latest message. If the
   same field is stated more than once with different values, the LAST stated value wins
   (the user corrected themselves). Do NOT guess or invent a value for a field never
   mentioned in any message — use null for that.

2. CURRENT-TURN FIELDS (meal_text, meal_type, intent): extract these ONLY from the LATEST
   message below (the last one in the conversation above). Do NOT pull meal_text/meal_type/
   intent from an earlier turn — a meal mentioned several messages ago should not resurface
   as "log this meal" again now.

Latest message: {message}

Return ONLY a valid JSON object with this exact structure — no explanation, no markdown:
{{
  "weight_kg": <number or null>,
  "height_cm": <number or null>,
  "age": <integer or null>,
  "gender": "male" or "female" or null,
  "activity_level": "sedentary" or "lightly_active" or "moderately_active" or "very_active" or "extra_active" or null,
  "goal": "lose" or "maintain" or "gain" or null,
  "goal_rate_kg_per_week": <number or null>,
  "meal_text": "<verbatim description of food/meal the user says they ate or are logging, or null>",
  "meal_type": "breakfast" or "lunch" or "dinner" or "snack" or null,
  "intent": "log_meal" or "set_profile" or "unknown"
}}

Important: "meal_text" must be null unless the LATEST message actually describes food or a
meal the user ate. Do not put unrelated questions, greetings, or profile-only messages
into "meal_text".

"intent" classifies the LATEST message only: "log_meal" if it describes food/a meal to log,
"set_profile" if it provides personal profile details (weight/height/age/gender/activity
level/goal), "unknown" if it does neither (or you are unsure)."""


class _ExtractedFieldsSchema(BaseModel):
    """llm_call validation schema for extract_request_fields's raw JSON
    output.

    Deliberately loose typing (plain `str` instead of Literal) for
    gender/activity_level/goal/meal_type: an invalid *value* for one of
    these (e.g. gender="unknown") is a domain-validation failure, surfaced
    downstream via CalcRequest construction ("Model produced an invalid
    profile") — not a schema-shape failure that should trigger llm_call's
    retry-then-raise path.

    `intent` is likewise typed as plain `str | None` rather than the real
    `Intent` enum (ADR-005 contract 2). If `intent` were typed as `Intent`
    directly, an unrecognized/omitted value from the model would fail
    Pydantic enum validation inside `schema(**data)` (llm_call.py), which
    llm_call treats as a schema-validation failure — triggering its
    retry-then-raise path instead of the graceful UNKNOWN coercion ADR-005
    requires ("never raise ValueError for an unrecognized intent string").
    So this field stays a loose `str | None` here, and the raw string is
    coerced to `Intent` (defaulting to `Intent.UNKNOWN` + a WARNING log for
    anything unrecognized or absent) in extract_request_fields, after
    llm_call has already returned successfully.
    """
    weight_kg: float | None = None
    height_cm: float | None = None
    age: int | None = None
    gender: str | None = None
    activity_level: str | None = None
    goal: str | None = None
    goal_rate_kg_per_week: float | None = None
    meal_text: str | None = None
    meal_type: str | None = None
    intent: str | None = None


def extract_request_fields(
    message: str,
    llm: BaseChatModel | None,
    conversation_history: list[str] | None = None,
) -> ParsedRequest:
    """Turn a free-text /api/agent message into structured request fields.

    One LLM call (ADR-003's `extract_request_fields`), replacing the ReAct
    loop's field-extraction responsibility with a single-shot structured
    extraction. `profile` is populated only if the FULL conversation
    (conversation_history + message) contains ALL of CalcRequest's required
    fields; otherwise None. `meal_text` is populated if the LATEST message
    describes a meal to log; `meal_type` defaults to "snack" when meal_text
    is present but no type was mentioned.

    `conversation_history` (ADR-008): prior USER messages from the current
    onboarding session, oldest first, NOT including `message` itself. When
    present, profile fields are extracted from the full transcript (so a
    field given two turns ago is not forgotten) while meal_text/meal_type/
    intent are still extracted from only `message` (the current turn) — see
    EXTRACTION_PROMPT's two-instruction split. Optional and defaulted so
    every existing call site (single-message extraction) is unaffected.

    The `llm` parameter is accepted to match ADR-003's sketch signature and
    to keep the call site consistent with the rest of the orchestrator, but
    this function always issues its own request in JSON mode via
    get_json_llm() (same pattern as meal_parse_agent.py::parse_meal) rather
    than reusing whatever mode `llm` was constructed in — plain chat models
    are not reliable at emitting bare JSON without format="json" forced at
    the client level. See report for this judgment call.
    """
    del llm  # accepted for ADR-003 signature parity; see docstring

    all_messages = (conversation_history or []) + [message]
    safe_message = message.replace("{", "{{").replace("}", "}}")
    conversation_block = "\n".join(
        f"Message {i}: {m.replace('{', '{{').replace('}', '}}')}" for i, m in enumerate(all_messages, start=1)
    )
    prompt = EXTRACTION_PROMPT.format(message=safe_message, conversation=conversation_block)
    json_llm = get_json_llm()

    log.debug("[extract_request_fields] calling llm_call")
    call_result = llm_call(
        name="extract_request_fields", prompt=prompt, schema=_ExtractedFieldsSchema, llm=json_llm,
    )
    raw = call_result.output
    log.debug(
        "[extract_request_fields] llm_call ok latency_ms=%.1f retry_count=%d",
        call_result.latency_ms, call_result.retry_count,
    )

    profile = None
    profile_fields = {k: getattr(raw, k) for k in _PROFILE_FIELD_NAMES}
    required_present = all(profile_fields[k] is not None for k in _PROFILE_FIELD_NAMES if k != "goal_rate_kg_per_week")
    if required_present:
        # goal_rate_kg_per_week has a schema default (0.5); drop it if absent
        # so CalcRequest applies that default rather than us hardcoding one.
        kwargs = {k: v for k, v in profile_fields.items() if v is not None}
        try:
            profile = CalcRequest(**kwargs)
        except Exception as e:
            raise ValueError(f"Model produced an invalid profile: {e}\nFields: {kwargs}")

    meal_text = raw.meal_text or None
    meal_type = raw.meal_type or None
    if meal_text and not meal_type:
        meal_type = "snack"

    # ADR-007 Action Item 4/5: reuse the same profile_fields presence check
    # above (not a second pass) to compute which required CalcRequest fields
    # are still null, for SlotFillPayload.missing.
    missing_profile_fields = [k for k in _REQUIRED_PROFILE_FIELD_NAMES if profile_fields[k] is None]

    # ADR-005 contract 2: `intent` is a soft signal, never a hard validation
    # gate. Coerce a missing/unrecognized value to Intent.UNKNOWN instead of
    # raising — see _ExtractedFieldsSchema's docstring for why this coercion
    # happens here (post-llm_call) rather than via Pydantic enum validation
    # inside the schema itself.
    if raw.intent is None:
        log.warning("[extract_request_fields] model omitted intent — coercing to UNKNOWN")
        intent = Intent.UNKNOWN
    else:
        try:
            intent = Intent(raw.intent)
        except ValueError:
            log.warning(
                "[extract_request_fields] unrecognized intent value=%r from model — coercing to UNKNOWN",
                raw.intent,
            )
            intent = Intent.UNKNOWN

    parsed = _ParsedRequestWithMissing(
        profile=profile, meal_text=meal_text, meal_type=meal_type, intent=intent,
        missing_profile_fields=missing_profile_fields,
    )
    log.debug(
        "[extract_request_fields] classified intent=%s from raw_fields=%s",
        intent.value, raw.model_dump(),
    )
    log.info(
        "[extract_request_fields] profile=%s meal_text=%s meal_type=%s intent=%s",
        "present" if parsed.profile else "absent", bool(parsed.meal_text), parsed.meal_type, intent.value,
    )
    return parsed


# ---------------------------------------------------------------------------
# compose_response — turns whatever combination of calc/meal results (both,
# either, or neither) into a human-readable AgentResponse.response string.
# ---------------------------------------------------------------------------

def compose_response(calc: CalcResponse | None, meal: dict | None) -> str:
    parts: list[str] = []

    if calc is not None:
        parts.append(
            f"Your BMR is {calc.bmr_kcal:.0f} kcal/day, TDEE is {calc.tdee_kcal:.0f} kcal/day, "
            f"and your calorie goal is {calc.calorie_goal_kcal:.0f} kcal/day."
        )

    if meal is not None:
        item_names = ", ".join(item.get("name", "item") for item in meal.get("items", []))
        total_kcal = meal.get("total_kcal")
        meal_type = meal.get("meal_type", "meal")
        # parse_meal only guarantees valid JSON, not a numeric total_kcal — a
        # small model can plausibly omit it or return null. Degrade gracefully
        # (drop the "(~N kcal)" clause) instead of crashing on `:.0f` format.
        kcal_suffix = f" (~{total_kcal:.0f} kcal)" if isinstance(total_kcal, (int, float)) else ""
        if item_names:
            parts.append(f"Logged {meal_type}: {item_names}{kcal_suffix}.")
        else:
            parts.append(f"Logged {meal_type}{kcal_suffix}.")

    if not parts:
        return (
            "I couldn't find any calorie-calculation profile fields or a meal description "
            "in your message. Could you tell me your weight, height, age, gender, activity "
            "level, and goal, or describe what you ate?"
        )

    return " ".join(parts)


# ---------------------------------------------------------------------------
# ADR-007 Action Item 6 -- recommendation trigger heuristic.
#
# The ADR explicitly leaves "when to recommend" as an open orchestration
# judgment call (Open Questions), not a fixed spec. Minimal, documented
# heuristic: a RECOMMENDATION is only composed when the client has already
# sent a *confirmed* profile as request context (AgentRequest.profile) AND
# the free-text message explicitly asks for one. This keeps the existing
# default behavior (no `profile` context passed) completely unaffected.
# ---------------------------------------------------------------------------

_RECOMMENDATION_KEYWORDS = (
    "recommend", "should i", "adjust my", "change my goal", "update my goal", "new goal",
)


def _wants_recommendation(message: str) -> bool:
    lowered = message.lower()
    return any(kw in lowered for kw in _RECOMMENDATION_KEYWORDS)


# ---------------------------------------------------------------------------
# Orchestrator — ADR-003 Action Item 6.
#
# Plain Python, no LLM loop: one structured-extraction call, then at most two
# deterministic/isolated steps (CalcPipeline, MealParseAgent) based on which
# fields extract_request_fields found. Persistence (save_meal) is explicitly
# out of scope here — ADR-003/ADR-001 still haven't implemented it.
# ---------------------------------------------------------------------------

def _run_agent_orchestrator(
    message: str,
    llm: BaseChatModel | None,
    profile: CalcRequest | None = None,
    trigger: str = "message",
    conversation_history: list[str] | None = None,
) -> AgentResponse:
    # ADR-005 contract 6: bind one correlation id for this request's entire
    # call tree (generates a UUID4 since routes.py doesn't yet supply one).
    # Purely additive infra — does not touch the presence-based dispatch
    # logic below; see ADR-005 sub-stage 1c for the Intent-routing change.
    with bind_correlation_id() as correlation_id:
        # ADR-007 Action Item 5: weekly_checkin short-circuits everything
        # else, including `message` content -- no LLM/pipeline call happens
        # on this path, so there is no ADR-007 Part-1 failure mode to guard
        # here (nothing that can raise httpx/ValueError).
        if trigger == "weekly_checkin":
            last_weight_kg = profile.weight_kg if profile is not None else None
            log.debug(
                "[orchestrator] decision handler=weekly_checkin intent=n/a outcome=composed "
                "message_type=%s latency_ms=%.1f correlation_id=%s",
                AgentMessageType.WEEKLY_CHECKIN.value, 0.0, correlation_id,
            )
            response_text = (
                "It's time for your weekly check-in — what's your current weight?"
                if last_weight_kg is None
                else (
                    f"It's time for your weekly check-in — your last recorded weight was "
                    f"{last_weight_kg:.1f} kg. What's your current weight today?"
                )
            )
            return AgentResponse(
                response=response_text,
                iterations_used=0,
                message_type=AgentMessageType.WEEKLY_CHECKIN,
                weekly_checkin=WeeklyCheckinPayload(last_weight_kg=last_weight_kg),
            )

        t_start = time.perf_counter()
        log.info("=" * 60)
        log.info("[orchestrator] correlation_id=%s Input: %s", correlation_id, message)

        # extract_request_fields and parse_meal both call llm_call(...)
        # internally (no internal try/except of their own, unlike the ReAct
        # loop's llm_with_tools.invoke calls). Same httpx/ValueError ->
        # HTTPException translation as _run_agent_react_loop /
        # routes.py's /api/parse-meal handler, applied here so NIM
        # outages or malformed-LLM-output don't surface as a bare 500.
        # ADR-006: get_llm()/get_json_llm() now wrap a retry+fallback
        # chain (services/agent_service.py imports get_llm) — a request only
        # reaches these handlers if every model in LLM_MODELS has already
        # exhausted its retries, so these are genuine full-chain failures.
        try:
            # Only pass conversation_history when actually supplied -- keeps
            # this call site source-compatible with every existing
            # extract_request_fields mock in tests/test_agent_service.py
            # (fixed (message, llm) signature) that pre-dates ADR-008 and
            # never receives a conversation_history in its own test setup.
            if conversation_history:
                parsed_request = extract_request_fields(message, llm, conversation_history=conversation_history)
            else:
                parsed_request = extract_request_fields(message, llm)

            calc = None
            calc_error: ValueError | None = None
            if parsed_request.profile:
                t0 = time.perf_counter()
                try:
                    calc = run_calc_pipeline(parsed_request.profile)
                    log.info("[orchestrator] CalcPipeline ran in %.1fms", (time.perf_counter() - t0) * 1000)
                except ValueError as e:
                    # ADR-007 Action Item 7: a calc-pipeline failure backing
                    # the profile_confirmation payload must degrade to INFO,
                    # not propagate as a 422 -- deferred to the composition
                    # section below (message_type dispatch) instead of the
                    # generic ValueError->422 translation a few lines down,
                    # which still applies unchanged to every other case
                    # (calc failure on a non-set_profile-intent message is
                    # not "backing one of the four ADR-007 payload types").
                    if parsed_request.intent == Intent.SET_PROFILE:
                        calc_error = e
                    else:
                        raise

            meal = None
            if parsed_request.meal_text:
                # ADR-005 Known Limitations item 2 (eval-parity gap): pass the
                # ORIGINAL raw `message`, not `parsed_request.meal_text` (an
                # LLM-reworded paraphrase produced by extract_request_fields),
                # into parse_meal. evals/run_eval.py scores parse_meal_text
                # against the user's real wording, so production must feed it
                # the same real wording to keep eval scores meaningful.
                # `parsed_request.meal_text`'s presence is still the routing
                # signal ("does this message contain a meal to log") -- only
                # the text argument passed to parse_meal changed. Routing
                # itself stays presence-based, not Intent-gated (ADR-005
                # contract 1: Intent is not a second router).
                log.debug(
                    "[orchestrator] intent=%s -- using raw message (not extracted "
                    "meal_text) for parse_meal to close eval-parity gap "
                    "(ADR-005 Known Limitations #2)",
                    parsed_request.intent.value,
                )
                t0 = time.perf_counter()
                meal = parse_meal(message, parsed_request.meal_type or "snack")
                log.info("[orchestrator] MealParseAgent ran in %.1fms", (time.perf_counter() - t0) * 1000)
        except httpx.ConnectError:
            log.error("[orchestrator] Cannot connect to NVIDIA NIM")
            raise HTTPException(status_code=503, detail="Cannot connect to NVIDIA NIM (integrate.api.nvidia.com).")
        except httpx.ReadError:
            log.error("[orchestrator] NVIDIA NIM dropped the connection")
            raise HTTPException(
                status_code=503,
                detail="NVIDIA NIM dropped the connection while all fallback models were exhausted.",
            )
        except httpx.HTTPStatusError as e:
            log.error("[orchestrator] NVIDIA NIM HTTP %d: %s", e.response.status_code, e.response.text[:200])
            raise HTTPException(
                status_code=502,
                detail=f"NVIDIA NIM returned HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.TimeoutException:
            log.error("[orchestrator] NVIDIA NIM timed out")
            raise HTTPException(
                status_code=504,
                detail="NVIDIA NIM timed out on every model in the fallback chain.",
            )
        except ValueError as e:
            log.error("[orchestrator] Validation error: %s", e)
            raise HTTPException(status_code=422, detail=str(e))

        # NOTE: persistence (save_meal) is intentionally NOT called here.
        # save_meal/get_daily_summary are unimplemented per ADR-003's Consequences
        # section and ADR-001 — real new scope, not authorized in this unit.
        # Also: no gating on `meal`/item `confidence` anywhere in this function —
        # confidence calibration is currently an inverted/untrustworthy signal
        # (39.6%, below the 50% no-signal line per the ADR-004 eval baseline).

        # iterations_used: there's no loop anymore, so this counts how many of
        # {calc, meal} actually ran (0, 1, or 2) as the closest honest analogue
        # to the old field's meaning ("how much work did this request cause").
        iterations_used = sum(1 for step in (calc, meal) if step is not None)

        # -------------------------------------------------------------------
        # ADR-007 Action Item 4: message_type + exactly one matching payload
        # field. Default is INFO + all four payloads None (today's behavior,
        # unchanged) -- the branches below are additive, evaluated in order,
        # mutually exclusive (if/elif chain, never more than one non-None
        # payload). Each branch is wrapped per Action Item 7: a failure while
        # composing a structured payload degrades to INFO with a plain
        # response string, never an unhandled exception.
        # -------------------------------------------------------------------
        message_type = AgentMessageType.INFO
        slot_fill = None
        profile_confirmation = None
        recommendation = None
        response_text = None

        if parsed_request.profile is not None and parsed_request.intent == Intent.SET_PROFILE:
            # Action Item 6: the user just supplied a complete profile via
            # free text -- show a confirmation with a computed preview
            # before it's persisted client-side. `calc` above was already
            # computed via run_calc_pipeline (the same deterministic
            # pipeline /api/calculate uses) for this exact profile, so reuse
            # it rather than invoking the pipeline a second time.
            try:
                if calc_error is not None:
                    raise calc_error
                preview = calc if calc is not None else run_calc_pipeline(parsed_request.profile)
                profile_confirmation = ProfileConfirmationPayload(profile=parsed_request.profile, preview=preview)
                message_type = AgentMessageType.PROFILE_CONFIRMATION
                response_text = (
                    f"Here's your profile summary — daily target {preview.calorie_goal_kcal:.0f} kcal "
                    f"(BMR {preview.bmr_kcal:.0f}, TDEE {preview.tdee_kcal:.0f}). Confirm to save it."
                )
                log.debug(
                    "[orchestrator] decision handler=profile_confirmation intent=%s outcome=composed "
                    "message_type=%s latency_ms=%.1f correlation_id=%s",
                    parsed_request.intent.value, message_type.value,
                    (time.perf_counter() - t_start) * 1000, correlation_id,
                )
            except (ValueError, TypeError) as e:
                log.warning(
                    "[orchestrator] decision handler=profile_confirmation outcome=fallback "
                    "message_type=%s error=%s correlation_id=%s",
                    AgentMessageType.INFO.value, e, correlation_id,
                )
                message_type = AgentMessageType.INFO
                profile_confirmation = None
                response_text = "I couldn't confirm your profile right now — try again in a moment."

        elif parsed_request.profile is None and parsed_request.intent == Intent.SET_PROFILE:
            # Action Item 4/5 support: the message clearly contains profile
            # info (LLM classified intent=set_profile) but not all required
            # fields -- ask for what's missing rather than silently dropping
            # the partial info on the floor.
            try:
                missing = list(
                    getattr(parsed_request, "missing_profile_fields", None) or _REQUIRED_PROFILE_FIELD_NAMES
                )
                slot_fill = SlotFillPayload(missing=missing)
                message_type = AgentMessageType.SLOT_FILL_QUESTION
                response_text = (
                    "I need a few more details before I can calculate your calorie goal: "
                    + ", ".join(missing) + "."
                )
                log.debug(
                    "[orchestrator] decision handler=slot_fill intent=%s outcome=composed "
                    "message_type=%s missing=%s latency_ms=%.1f correlation_id=%s",
                    parsed_request.intent.value, message_type.value, missing,
                    (time.perf_counter() - t_start) * 1000, correlation_id,
                )
            except (ValueError, TypeError) as e:
                log.warning(
                    "[orchestrator] decision handler=slot_fill outcome=fallback "
                    "message_type=%s error=%s correlation_id=%s",
                    AgentMessageType.INFO.value, e, correlation_id,
                )
                message_type = AgentMessageType.INFO
                slot_fill = None
                response_text = "I couldn't process your profile details right now — try again in a moment."

        elif profile is not None and _wants_recommendation(message):
            # Recommendation trigger heuristic -- see _wants_recommendation's
            # docstring/comment above. Uses the client's already-confirmed
            # `profile` request context (AgentRequest.profile), not the
            # message-extracted `parsed_request.profile`.
            try:
                rec_preview = run_calc_pipeline(profile)
                rationale = (
                    f"Based on your current profile ({profile.goal} at "
                    f"{profile.goal_rate_kg_per_week}kg/week), your recommended calorie goal is "
                    f"{rec_preview.calorie_goal_kcal:.0f} kcal/day."
                )
                recommendation = RecommendationPayload(
                    calorie_goal_kcal=rec_preview.calorie_goal_kcal,
                    tdee_kcal=rec_preview.tdee_kcal,
                    bmr_kcal=rec_preview.bmr_kcal,
                    rationale=rationale,
                )
                message_type = AgentMessageType.RECOMMENDATION
                response_text = rationale
                log.debug(
                    "[orchestrator] decision handler=recommendation intent=%s outcome=composed "
                    "message_type=%s latency_ms=%.1f correlation_id=%s",
                    parsed_request.intent.value, message_type.value,
                    (time.perf_counter() - t_start) * 1000, correlation_id,
                )
            except (ValueError, TypeError) as e:
                log.warning(
                    "[orchestrator] decision handler=recommendation outcome=fallback "
                    "message_type=%s error=%s correlation_id=%s",
                    AgentMessageType.INFO.value, e, correlation_id,
                )
                message_type = AgentMessageType.INFO
                recommendation = None
                response_text = "I couldn't put together a recommendation right now — try again in a moment."

        if response_text is None:
            response_text = compose_response(calc, meal)

        total_ms = (time.perf_counter() - t_start) * 1000
        log.info(
            "[orchestrator] Done  correlation_id=%s  iterations_used=%d  message_type=%s  total_time=%.1fms",
            correlation_id, iterations_used, message_type.value, total_ms,
        )

        return AgentResponse(
            response=response_text,
            iterations_used=iterations_used,
            message_type=message_type,
            slot_fill=slot_fill,
            profile_confirmation=profile_confirmation,
            recommendation=recommendation,
        )


def run_agent(
    message: str,
    llm: BaseChatModel | None,
    profile: CalcRequest | None = None,
    trigger: str = "message",
    conversation_history: list[str] | None = None,
) -> AgentResponse:
    """Public entry point for /api/agent.

    ADR-007 Action Item 5: gained optional `profile`/`trigger` (mirroring
    AgentRequest's new fields) so the orchestrator can produce
    weekly_checkin/recommendation-typed responses using client-supplied
    context. ADR-008: gained optional `conversation_history` (mirroring
    AgentRequest.conversation_history) so multi-turn onboarding slot-filling
    re-extracts profile fields over the full transcript instead of losing
    fields given in earlier turns. All default such that an old call site
    (`run_agent(message, llm)`) is unchanged.

    Routes to the new Orchestrator by default; set USE_ORCHESTRATOR=false to
    roll back to the old ReAct loop (_run_agent_react_loop) without a code
    change (see calai_backend/config.py). The ReAct loop does not consume
    profile/trigger/conversation_history -- it predates ADR-007/ADR-008 and
    is not being extended here (ADR-003 Migration Plan: kept for rollback
    only).
    """
    if USE_ORCHESTRATOR:
        return _run_agent_orchestrator(
            message, llm, profile=profile, trigger=trigger, conversation_history=conversation_history,
        )
    return _run_agent_react_loop(message, llm)


# ---------------------------------------------------------------------------
# Old ReAct loop — kept fully intact per ADR-003 Migration Plan step 4
# ("Keep the old ReAct loop path behind a flag or in git history until the
# orchestrator passes the same eval suite at parity or better"). Removal is
# ADR-003 Action Item 8, not authorized in this unit.
# ---------------------------------------------------------------------------

def _run_agent_react_loop(message: str, llm: BaseChatModel | None) -> AgentResponse:
    t_start = time.perf_counter()
    log.info("=" * 60)
    log.info("[run_agent] Input: %s", message)
    log.info("[run_agent] MaxSteps: %d", MAX_STEPS)

    tools = get_tools()
    tools_dict = get_dict()
    # ADR-006 ordering constraint: `llm` (whatever routes.py's DI passed in)
    # is not used to .bind_tools() directly — RunnableRetry/
    # RunnableWithFallbacks (what providers/llm.py's get_llm() now returns)
    # are not BaseChatModel and have no .bind_tools(). Rebuild via
    # get_llm(tools=tools), which binds tools on each raw client BEFORE
    # retry/fallback wrapping. The `llm` parameter is kept for signature
    # parity with _run_agent_orchestrator and existing callers/tests.
    del llm
    llm_with_tools = get_llm(tools=tools)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=message),
    ]

    for iteration in range(1, MAX_STEPS + 1):
        log.info("--- Iteration %d ---", iteration)

        t0 = time.perf_counter()
        try:
            ai_message = llm_with_tools.invoke(messages)
        except httpx.ConnectError:
            log.error("[ERROR] Cannot connect to NVIDIA NIM")
            raise HTTPException(status_code=503, detail="Cannot connect to NVIDIA NIM (integrate.api.nvidia.com).")
        except httpx.ReadError:
            log.error("[ERROR] NVIDIA NIM dropped the connection")
            raise HTTPException(
                status_code=503,
                detail="NVIDIA NIM dropped the connection while all fallback models were exhausted.",
            )
        except httpx.HTTPStatusError as e:
            log.error("[ERROR] NVIDIA NIM HTTP %d: %s", e.response.status_code, e.response.text[:200])
            raise HTTPException(
                status_code=502,
                detail=f"NVIDIA NIM returned HTTP {e.response.status_code}: {e.response.text[:200]}",
            )
        except httpx.TimeoutException:
            log.error("[ERROR] NVIDIA NIM timed out on iteration %d", iteration)
            raise HTTPException(
                status_code=504,
                detail="NVIDIA NIM timed out on every model in the fallback chain.",
            )

        llm_ms = (time.perf_counter() - t0) * 1000
        log.info("[LLM call]       %.1fms  tool_calls=%s", llm_ms, [c["name"] for c in ai_message.tool_calls])

        if not ai_message.tool_calls:
            total_ms = (time.perf_counter() - t_start) * 1000
            log.info("[Final Answer]   iterations=%d  total_time=%.1fms", iteration, total_ms)
            return AgentResponse(response=ai_message.content or "", iterations_used=iteration)

        messages.append(ai_message)
        for tool_call in ai_message.tool_calls:
            tool_name = tool_call["name"]
            # Some models (observed: openai/gpt-oss-20b via NVIDIA NIM, which
            # emits OpenAI's "Harmony" multi-channel format) leak a trailing
            # special-token tag onto the tool name coming out of
            # ai_message.tool_calls, e.g. "calculate_tdee<|channel|>commentary"
            # instead of "calculate_tdee". Strip anything from the first
            # "<|...|>"-style marker onward before using the name to look up
            # the tool, so this doesn't corrupt dispatch. Log when this
            # actually changes something so a genuinely different "unknown
            # tool" bug doesn't get silently swallowed by this.
            harmony_marker = tool_name.find("<|")
            if harmony_marker != -1:
                sanitized_name = tool_name[:harmony_marker]
                log.warning(
                    "[Tool Selected]  sanitized Harmony-format tool name leak: %r -> %r",
                    tool_name, sanitized_name,
                )
                tool_name = sanitized_name
            tool_args = tool_call["args"]
            log.info("[Tool Selected]  %s  args=%s", tool_name, tool_args)

            tool_fn = tools_dict.get(tool_name)
            if tool_fn is None:
                raise HTTPException(status_code=500, detail=f"Unknown tool: {tool_name}")

            t0 = time.perf_counter()
            try:
                observation = tool_fn.invoke(tool_args)
            except (httpx.ConnectError, httpx.ReadError):
                raise HTTPException(status_code=503, detail="NVIDIA NIM is not reachable during tool call.")
            except httpx.HTTPStatusError as e:
                raise HTTPException(
                    status_code=502,
                    detail=f"NVIDIA NIM returned HTTP {e.response.status_code}: {e.response.text[:200]}",
                )
            except httpx.TimeoutException:
                raise HTTPException(
                    status_code=504,
                    detail="NVIDIA NIM timed out on every model in the fallback chain during tool call.",
                )
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))
            log.info("[Tool Result]    %s  (%.1fms)", observation, (time.perf_counter() - t0) * 1000)

            content = str(observation) if observation is not None else "Tool completed successfully."
            messages.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))

    total_ms = (time.perf_counter() - t_start) * 1000
    log.error("[ERROR] Max iterations (%d) reached  total_time=%.1fms", MAX_STEPS, total_ms)
    raise HTTPException(status_code=500, detail="Agent reached max iterations without a final answer.")
