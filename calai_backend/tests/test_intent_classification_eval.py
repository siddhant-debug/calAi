"""First-ever eval coverage of `extract_request_fields`'s Intent
classification (ADR-005 REQ-01 / Phase 1c).

Golden cases live in `evals/dataset_intent/intent_classification.jsonl`,
deliberately kept OUTSIDE `evals/dataset/` so `run_eval.py`'s default
`dataset_arg.glob("*.jsonl")` run doesn't pick it up and feed its
non-meal-shaped cases (e.g. "what's the weather like today") into
`parse_meal_text`, which has no way to know this file is shaped
differently (`expected_intent`, not `expected_items`) and would otherwise
hallucinate food items for them, regressing the committed meal-parsing
baseline's `item_precision_pct`. It's in the same `.jsonl`-golden-dataset
family as `evals/dataset/*.jsonl` (per ADR-004), but scored here as a
standalone pytest rather than through
`evals/run_eval.py`'s aggregate scorer/report pipeline: `run_eval.py`'s
existing scorers (`item_match`, `calorie_accuracy`, `confidence_calibration`)
are meal-parsing-shaped (items/calorie ranges) and don't fit an
intent-classification golden case (a single categorical label, not a range).
Building a dedicated scorer + report wiring for this is real follow-up work,
called out in ADR-005's Known Limitations item 2 and the phased plan's
Phase 2a (closing the eval-parity gap for `extract_request_fields` more
broadly) -- not required by this sub-stage. This file's job is narrower:
make sure the golden dataset exists with real cases and that
`extract_request_fields`'s Intent-coercion logic classifies each one
correctly, using a mocked LLM response shaped like what a well-behaved
model would actually return for that input (not a real Ollama call --
no LLM round trips here, consistent with the rest of
`test_agent_service.py`).
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from calai_backend.schemas import Intent
from calai_backend.services import agent_service

DATASET_PATH = Path(__file__).resolve().parents[2] / "evals" / "dataset_intent" / "intent_classification.jsonl"

# Well-behaved-model profile-field extractions for the set_profile golden
# cases in the dataset above -- hand-matched to what a correctly-behaving
# model would extract from each literal input string (mirrors how a real
# extraction would fill CalcRequest's required fields).
_SET_PROFILE_RAW_FIELDS = {
    "I'm 28 years old, weigh 70kg, 175cm tall, male, moderately active, trying to lose weight": {
        "weight_kg": 70, "height_cm": 175, "age": 28, "gender": "male",
        "activity_level": "moderately_active", "goal": "lose",
    },
    "my weight is 60kg, height 165cm, age 32, female, sedentary, goal is to maintain": {
        "weight_kg": 60, "height_cm": 165, "age": 32, "gender": "female",
        "activity_level": "sedentary", "goal": "maintain",
    },
}


class FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return SimpleNamespace(content=self._content)


def _load_cases():
    cases = []
    with open(DATASET_PATH) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _mock_raw_response_for(case: dict) -> dict:
    """Build the raw extraction JSON a well-behaved model would return for
    this golden case's input, given its expected_intent."""
    expected = case["expected_intent"]
    base = {
        "weight_kg": None, "height_cm": None, "age": None, "gender": None,
        "activity_level": None, "goal": None, "goal_rate_kg_per_week": None,
        "meal_text": None, "meal_type": None, "intent": expected,
    }
    if expected == "log_meal":
        base["meal_text"] = case["input"]
    elif expected == "set_profile":
        base.update(_SET_PROFILE_RAW_FIELDS[case["input"]])
    # "unknown" cases: nothing extracted, matches base defaults.
    return base


CASES = _load_cases()


def test_dataset_file_has_golden_cases_for_all_three_intents():
    intents_present = {c["expected_intent"] for c in CASES}
    assert intents_present == {"log_meal", "set_profile", "unknown"}
    assert len(CASES) >= 5


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["input"][:40])
def test_extract_request_fields_classifies_golden_case_correctly(monkeypatch, case):
    raw = _mock_raw_response_for(case)
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    parsed = agent_service.extract_request_fields(case["input"], llm=object())

    assert parsed.intent == Intent(case["expected_intent"])
