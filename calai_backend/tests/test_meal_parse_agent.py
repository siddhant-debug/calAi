"""Tests for services/meal_parse_agent.py and tools/meal_parser.py's thin
wrapper (ADR-003 Action Item 3).

No real LLM calls here — get_json_llm() is mocked. The actual parse-quality
gate is the eval harness in evals/ (ADR-004); this suite only guards the
relocation and JSON/error handling, which is deterministic code around the
one nondeterministic call.
"""
import json
import logging
from types import SimpleNamespace

import pytest

from calai_backend.services import meal_parse_agent
from calai_backend.tools import meal_parser


class FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return SimpleNamespace(content=self._content)


class SequenceLLM:
    """Fake chat model returning one canned response per `.invoke()` call,
    in order — used to exercise llm_call's retry-then-succeed path through
    the real parse_meal call site (ADR-005 REQ-04)."""

    def __init__(self, contents):
        self._contents = list(contents)

    def invoke(self, messages):
        return SimpleNamespace(content=self._contents.pop(0))


def test_parse_meal_parses_valid_json(monkeypatch):
    fake_result = {
        "items": [
            {
                "name": "banana",
                "quantity": 1,
                "unit": "piece",
                "calories_kcal": 105,
                "protein_g": 1.3,
                "carbs_g": 27,
                "fat_g": 0.4,
                "confidence": "high",
            }
        ],
        "total_kcal": 105,
        "meal_type": "snack",
    }
    monkeypatch.setattr(
        meal_parse_agent, "get_json_llm", lambda: FakeLLM(json.dumps(fake_result))
    )

    result = meal_parse_agent.parse_meal("one banana", "snack")

    assert result == fake_result


def test_parse_meal_raises_valueerror_on_malformed_json(monkeypatch):
    monkeypatch.setattr(
        meal_parse_agent, "get_json_llm", lambda: FakeLLM("not valid json{{{")
    )

    with pytest.raises(ValueError, match="Model returned invalid JSON"):
        meal_parse_agent.parse_meal("one banana", "snack")


def test_parse_meal_retries_once_through_llm_call_then_succeeds(monkeypatch):
    """ADR-005 REQ-04: parse_meal now calls llm_call internally, which
    retries once on malformed JSON before raising. Before this migration
    there was no retry — a first malformed response raised immediately.
    This confirms the retry now works through the real parse_meal call
    site, not just llm_call in isolation (see test_llm_call.py)."""
    fake_result = {
        "items": [
            {
                "name": "banana",
                "quantity": 1,
                "unit": "piece",
                "calories_kcal": 105,
                "protein_g": 1.3,
                "carbs_g": 27,
                "fat_g": 0.4,
                "confidence": "high",
            }
        ],
        "total_kcal": 105,
        "meal_type": "snack",
    }
    monkeypatch.setattr(
        meal_parse_agent, "get_json_llm",
        lambda: SequenceLLM(["not valid json{{{", json.dumps(fake_result)]),
    )

    result = meal_parse_agent.parse_meal("one banana", "snack")

    assert result == fake_result


def test_parse_meal_raises_valueerror_on_invalid_meal_type():
    with pytest.raises(ValueError, match="meal_type must be one of"):
        meal_parse_agent.parse_meal("one banana", "brunch")


# ---------------------------------------------------------------------------
# ADR-005 REQ-05/contract 6 — WARNING: confidence present but not gated on
# ---------------------------------------------------------------------------

def test_parse_meal_logs_confidence_not_gated_warning_once_per_call(monkeypatch, caplog):
    fake_result = {
        "items": [
            {
                "name": "banana",
                "quantity": 1,
                "unit": "piece",
                "calories_kcal": 105,
                "protein_g": 1.3,
                "carbs_g": 27,
                "fat_g": 0.4,
                "confidence": "high",
            }
        ],
        "total_kcal": 105,
        "meal_type": "snack",
    }
    monkeypatch.setattr(
        meal_parse_agent, "get_json_llm", lambda: FakeLLM(json.dumps(fake_result))
    )
    caplog.set_level(logging.WARNING, logger="calai_backend.services.meal_parse_agent")

    meal_parse_agent.parse_meal("one banana", "snack")

    matching = [
        r for r in caplog.records
        if r.levelno == logging.WARNING and "confidence field present but not gated on" in r.getMessage()
    ]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# tools/meal_parser.py::parse_meal_text — the relocation's thin wrapper
# ---------------------------------------------------------------------------

def test_parse_meal_text_delegates_to_service(monkeypatch):
    calls = []

    def fake_parse_meal(meal_text, meal_type):
        calls.append((meal_text, meal_type))
        return {"items": [], "total_kcal": 0, "meal_type": meal_type}

    monkeypatch.setattr(meal_parser, "parse_meal", fake_parse_meal)

    result = meal_parser.parse_meal_text("two eggs", "breakfast")

    assert calls == [("two eggs", "breakfast")]
    assert result == {"items": [], "total_kcal": 0, "meal_type": "breakfast"}


def test_parse_meal_text_default_meal_type_is_snack(monkeypatch):
    calls = []
    monkeypatch.setattr(
        meal_parser,
        "parse_meal",
        lambda meal_text, meal_type: calls.append((meal_text, meal_type)),
    )

    meal_parser.parse_meal_text("a handful of chips")

    assert calls == [("a handful of chips", "snack")]
