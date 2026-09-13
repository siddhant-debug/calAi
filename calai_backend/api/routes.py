import logging
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import ValidationError

from calai_backend.schemas import (
    AgentRequest,
    AgentResponse,
    CalcRequest,
    CalcResponse,
    MealParseRequest,
    MealParseResponse,
)
from calai_backend.services.agent_service import run_agent
from calai_backend.services.calc_pipeline import run_calc_pipeline
from calai_backend.tools.meal_parser import parse_meal_text

log = logging.getLogger("calai.routes")

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /api/calculate  — direct tool calls, no LLM
# ---------------------------------------------------------------------------

@router.post("/calculate", response_model=CalcResponse)
def calculate(req: CalcRequest) -> CalcResponse:
    """Calculate BMR → TDEE → calorie goal from raw user stats in one shot."""
    t_start = time.perf_counter()
    log.info("=" * 60)
    log.info("[/api/calculate] Input: %s", req.model_dump())

    try:
        result = run_calc_pipeline(req)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    log.info("[/api/calculate] Total: %.1fms", (time.perf_counter() - t_start) * 1000)
    return result


# ---------------------------------------------------------------------------
# POST /api/parse-meal  — nested LLM call to extract nutrition from text
# ---------------------------------------------------------------------------

@router.post("/parse-meal", response_model=MealParseResponse)
def parse_meal(req: MealParseRequest) -> MealParseResponse:
    """Parse a natural-language meal description into structured nutrition data."""
    t_start = time.perf_counter()
    log.info("=" * 60)
    log.info("[/api/parse-meal] meal_type=%s  text=%r", req.meal_type, req.meal_text)

    try:
        result = parse_meal_text(req.meal_text, req.meal_type)
    except httpx.ConnectError:
        log.error("[/api/parse-meal] Cannot connect to NVIDIA NIM")
        raise HTTPException(
            status_code=503,
            detail="Cannot connect to NVIDIA NIM (integrate.api.nvidia.com).",
        )
    except httpx.ReadError:
        raise HTTPException(
            status_code=503,
            detail="NVIDIA NIM dropped the connection while all fallback models were exhausted.",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"NVIDIA NIM returned HTTP {e.response.status_code}: {e.response.text[:200]}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail="NVIDIA NIM timed out on every model in the fallback chain.",
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
    log.info("[/api/parse-meal] total_kcal=%s  items=%d  total_time=%.1fms",
             result.get("total_kcal"), len(result.get("items", [])), latency_ms)

    try:
        return MealParseResponse(**result, model_latency_ms=latency_ms)
    except ValidationError as e:
        raise HTTPException(status_code=502, detail=f"Model returned malformed data: {e}")


# ---------------------------------------------------------------------------
# POST /api/agent  — ReAct loop, returns LLM response
# ---------------------------------------------------------------------------

@router.post("/agent", response_model=AgentResponse)
def agent(req: AgentRequest) -> AgentResponse:
    """Run the CalAI agent and return the final LLM response.

    ADR-006: no longer builds an LLM via `Depends(get_llm)` at the route
    boundary. FastAPI DI ran before the tool list was known, and calling
    `.bind_tools()` on the retry/fallback-wrapped object `get_llm()` now
    returns would fail (`RunnableWithFallbacks` has no `.bind_tools()`).
    Neither downstream path needs a pre-built client anyway: the
    orchestrator builds its own `get_json_llm()` internally
    (agent_service.py::extract_request_fields), and the ReAct loop builds
    its own tool-bound `get_llm(tools=tools)` internally
    (agent_service.py::_run_agent_react_loop). `llm=None` is passed for
    signature parity with `run_agent(message, llm)`.
    """
    return run_agent(req.message, None, profile=req.profile, trigger=req.trigger)
