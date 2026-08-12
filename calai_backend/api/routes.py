import logging
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException
from langchain_core.language_models import BaseChatModel
from pydantic import ValidationError

from calai_backend.config import MODEL_NAME, OLLAMA_BASE_URL
from calai_backend.providers.llm import get_llm
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
        log.error("[/api/parse-meal] Cannot connect to Ollama at %s", OLLAMA_BASE_URL)
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to Ollama at {OLLAMA_BASE_URL}. Run `ollama serve`.",
        )
    except httpx.ReadError:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama dropped the connection — model '{MODEL_NAME}' may not be downloaded.",
        )
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Ollama returned HTTP {e.response.status_code}: {e.response.text[:200]}",
        )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail=f"Ollama timed out — model '{MODEL_NAME}' may be overloaded.",
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
def agent(req: AgentRequest, llm: BaseChatModel = Depends(get_llm)) -> AgentResponse:
    """Run the CalAI ReAct agent and return the final LLM response."""
    return run_agent(req.message, llm)
