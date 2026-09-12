from typing import List

from pydantic import BaseModel

from calai_backend.logging_config import get_logger
from calai_backend.providers.llm import get_json_llm
from calai_backend.schemas import MealItem
from calai_backend.services.llm_call import llm_call

log = get_logger(__name__)

MEAL_EXTRACTION_PROMPT = """You are a nutrition data extractor. The user will describe a meal in natural language.
Extract each food item and estimate its nutritional content based on typical serving sizes and standard nutrition data.

For each item, also report your confidence in the estimate as "high", "medium", or "low".
Use "high" when the food and portion are unambiguous (e.g. "2 eggs", "1 slice of toast").
Use "medium" when the food is clear but the portion is approximate (e.g. "a bowl of rice").
Use "low" when the food itself, its portion, or its preparation is vague or unusual
(e.g. "some snacks", "a plate of stuff").

Return ONLY a valid JSON object with this exact structure — no explanation, no markdown:
{{
  "items": [
    {{
      "name": "food name",
      "quantity": <number>,
      "unit": "piece/g/ml/cup/etc",
      "calories_kcal": <number>,
      "protein_g": <number>,
      "carbs_g": <number>,
      "fat_g": <number>,
      "confidence": "high/medium/low"
    }}
  ],
  "total_kcal": <sum of all calories_kcal>,
  "meal_type": "{meal_type}"
}}

Meal description: {meal_text}"""


class _MealParseSchema(BaseModel):
    """llm_call validation schema for parse_meal's output.

    Mirrors schemas.py::MealItem/MealParseResponse's shape minus
    model_latency_ms — that field is added later by
    api/routes.py's /api/parse-meal handler, it is not part of the LLM's
    own JSON output.
    """
    items: List[MealItem]
    total_kcal: float
    meal_type: str


def parse_meal(meal_text: str, meal_type: str = "snack") -> dict:
    """Parse a natural-language meal description into structured nutrition data.

    Owns: prompt construction and the LLM call for the meal-parsing step.
    JSON parsing and schema validation are delegated to
    services/llm_call.py::llm_call (ADR-005 contract 5) — same
    malformed-JSON -> ValueError contract as before, only relocated. This
    is the sole nondeterministic component in the pipeline (see ADR-003),
    and the subject of the ADR-004 eval harness.
    """
    valid_meal_types = ("breakfast", "lunch", "dinner", "snack")
    if meal_type not in valid_meal_types:
        raise ValueError(f"meal_type must be one of: {valid_meal_types}")

    safe_text = meal_text.replace("{", "{{").replace("}", "}}")
    prompt = MEAL_EXTRACTION_PROMPT.format(meal_text=safe_text, meal_type=meal_type)
    llm = get_json_llm()

    log.debug("parse_meal calling llm_call meal_type=%s", meal_type)
    call_result = llm_call(name="parse_meal", prompt=prompt, schema=_MealParseSchema, llm=llm)

    result = call_result.output.model_dump(mode="json")
    log.debug(
        "parse_meal ok latency_ms=%.1f retry_count=%d total_kcal=%s items=%d",
        call_result.latency_ms, call_result.retry_count,
        result.get("total_kcal"), len(result.get("items", [])),
    )
    # ADR-004 baseline: confidence calibration is 39.6%, below the 50%
    # no-signal line — a known, unaddressed limitation. Logged here (not
    # just a code comment) per ADR-005 contract 6's WARNING vocabulary, so
    # the fact that confidence exists but isn't gated on is visible at
    # runtime, once per meal-parse call.
    log.warning(
        "confidence field present but not gated on — known miscalibration, "
        "see ADR-004/ADR-005 Known Limitations"
    )
    return result
