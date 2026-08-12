"""Tests for calai_backend/schemas.py's ADR-005 contract 1/2 additions:
Intent(str, Enum) and ParsedRequest.intent (new required field).

Exact-value / exact-schema-behavior tests, no LLM calls -- matches the
deterministic-schema-test convention used elsewhere in this suite.
"""
import pytest
from pydantic import ValidationError

from calai_backend.schemas import Intent, ParsedRequest


# ---------------------------------------------------------------------------
# Intent enum
# ---------------------------------------------------------------------------

def test_intent_has_exactly_three_expected_values():
    assert {member.value for member in Intent} == {"log_meal", "set_profile", "unknown"}


def test_intent_member_names_map_to_expected_values():
    assert Intent.LOG_MEAL.value == "log_meal"
    assert Intent.SET_PROFILE.value == "set_profile"
    assert Intent.UNKNOWN.value == "unknown"


# ---------------------------------------------------------------------------
# ParsedRequest.intent
# ---------------------------------------------------------------------------

def test_parsed_request_without_intent_raises_validation_error():
    with pytest.raises(ValidationError, match="intent"):
        ParsedRequest(profile=None, meal_text=None, meal_type=None)


@pytest.mark.parametrize("intent_value", [Intent.LOG_MEAL, Intent.SET_PROFILE, Intent.UNKNOWN])
def test_parsed_request_accepts_all_three_valid_intent_values(intent_value):
    parsed = ParsedRequest(profile=None, meal_text=None, meal_type=None, intent=intent_value)

    assert parsed.intent == intent_value
