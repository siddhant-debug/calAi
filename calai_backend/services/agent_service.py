import time

import httpx
from fastapi import HTTPException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from calai_backend.config import MAX_STEPS, USE_ORCHESTRATOR
from calai_backend.logging_config import bind_correlation_id, get_logger
from calai_backend.prompts.calai_prompt import SYSTEM_PROMPT
from calai_backend.providers.llm import get_json_llm, get_llm
from calai_backend.schemas import AgentResponse, CalcRequest, CalcResponse, Intent, ParsedRequest
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

EXTRACTION_PROMPT = """You are a structured data extractor for a calorie-tracking app.
Read the user's message and extract ONLY the fields explicitly present in it.
Do NOT guess or invent values for anything not mentioned — use null for any field that is absent.

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

Important: "meal_text" must be null unless the message actually describes food or a
meal the user ate. Do not put unrelated questions, greetings, or profile-only messages
into "meal_text".

"intent" classifies the overall message: "log_meal" if it describes food/a meal to log,
"set_profile" if it provides personal profile details (weight/height/age/gender/activity
level/goal), "unknown" if it does neither (or you are unsure).

User message: {message}"""


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


def extract_request_fields(message: str, llm: BaseChatModel | None) -> ParsedRequest:
    """Turn a free-text /api/agent message into structured request fields.

    One LLM call (ADR-003's `extract_request_fields`), replacing the ReAct
    loop's field-extraction responsibility with a single-shot structured
    extraction. `profile` is populated only if the message contains ALL of
    CalcRequest's required fields; otherwise None. `meal_text` is populated
    if the message describes a meal to log; `meal_type` defaults to "snack"
    when meal_text is present but no type was mentioned.

    The `llm` parameter is accepted to match ADR-003's sketch signature and
    to keep the call site consistent with the rest of the orchestrator, but
    this function always issues its own request in JSON mode via
    get_json_llm() (same pattern as meal_parse_agent.py::parse_meal) rather
    than reusing whatever mode `llm` was constructed in — plain chat models
    are not reliable at emitting bare JSON without format="json" forced at
    the client level. See report for this judgment call.
    """
    del llm  # accepted for ADR-003 signature parity; see docstring

    safe_message = message.replace("{", "{{").replace("}", "}}")
    prompt = EXTRACTION_PROMPT.format(message=safe_message)
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

    parsed = ParsedRequest(profile=profile, meal_text=meal_text, meal_type=meal_type, intent=intent)
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
# Orchestrator — ADR-003 Action Item 6.
#
# Plain Python, no LLM loop: one structured-extraction call, then at most two
# deterministic/isolated steps (CalcPipeline, MealParseAgent) based on which
# fields extract_request_fields found. Persistence (save_meal) is explicitly
# out of scope here — ADR-003/ADR-001 still haven't implemented it.
# ---------------------------------------------------------------------------

def _run_agent_orchestrator(message: str, llm: BaseChatModel | None) -> AgentResponse:
    # ADR-005 contract 6: bind one correlation id for this request's entire
    # call tree (generates a UUID4 since routes.py doesn't yet supply one).
    # Purely additive infra — does not touch the presence-based dispatch
    # logic below; see ADR-005 sub-stage 1c for the Intent-routing change.
    with bind_correlation_id() as correlation_id:
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
            parsed_request = extract_request_fields(message, llm)

            calc = None
            if parsed_request.profile:
                t0 = time.perf_counter()
                calc = run_calc_pipeline(parsed_request.profile)
                log.info("[orchestrator] CalcPipeline ran in %.1fms", (time.perf_counter() - t0) * 1000)

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

        response_text = compose_response(calc, meal)
        total_ms = (time.perf_counter() - t_start) * 1000
        log.info(
            "[orchestrator] Done  correlation_id=%s  iterations_used=%d  total_time=%.1fms",
            correlation_id, iterations_used, total_ms,
        )

        return AgentResponse(response=response_text, iterations_used=iterations_used)


def run_agent(message: str, llm: BaseChatModel | None) -> AgentResponse:
    """Public entry point for /api/agent. Signature is unchanged (ADR-003).

    Routes to the new Orchestrator by default; set USE_ORCHESTRATOR=false to
    roll back to the old ReAct loop (_run_agent_react_loop) without a code
    change (see calai_backend/config.py).
    """
    if USE_ORCHESTRATOR:
        return _run_agent_orchestrator(message, llm)
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
