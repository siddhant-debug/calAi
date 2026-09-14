"""Tests for services/agent_service.py's ADR-003 Action Items 5-6:
extract_request_fields, compose_response, and the Orchestrator
(_run_agent_orchestrator) / run_agent dispatch.

No real LLM calls — get_json_llm() is mocked, same pattern as
test_meal_parse_agent.py. The old ReAct loop (_run_agent_react_loop) is
untouched logic (byte-identical rename) and already implicitly covered by
whatever exercised run_agent pre-refactor; this file only covers what's new.
"""
import json
import logging
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from calai_backend.schemas import (
    AgentMessageType,
    AgentResponse,
    CalcRequest,
    CalcResponse,
    Intent,
    ParsedRequest,
)
from calai_backend.services import agent_service
from calai_backend.services.calc_pipeline import run_calc_pipeline


class FakeLLM:
    def __init__(self, content):
        self._content = content

    def invoke(self, messages):
        return SimpleNamespace(content=self._content)


class SequenceLLM:
    """Fake chat model returning one canned response per `.invoke()` call,
    in order — used to exercise llm_call's retry-then-succeed path through
    the real extract_request_fields call site (ADR-005 REQ-04)."""

    def __init__(self, contents):
        self._contents = list(contents)

    def invoke(self, messages):
        return SimpleNamespace(content=self._contents.pop(0))


FULL_PROFILE_FIELDS = {
    "weight_kg": 75,
    "height_cm": 178,
    "age": 30,
    "gender": "male",
    "activity_level": "moderately_active",
    "goal": "lose",
    "goal_rate_kg_per_week": 0.5,
}


def _raw(**overrides):
    base = {
        "weight_kg": None,
        "height_cm": None,
        "age": None,
        "gender": None,
        "activity_level": None,
        "goal": None,
        "goal_rate_kg_per_week": None,
        "meal_text": None,
        "meal_type": None,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# extract_request_fields
# ---------------------------------------------------------------------------

def test_extract_request_fields_full_profile_and_meal(monkeypatch):
    raw = _raw(**FULL_PROFILE_FIELDS, meal_text="two eggs", meal_type="breakfast")
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    parsed = agent_service.extract_request_fields("some message", llm=object())

    assert isinstance(parsed, ParsedRequest)
    assert isinstance(parsed.profile, CalcRequest)
    assert parsed.profile.weight_kg == 75
    assert parsed.profile.gender == "male"
    assert parsed.meal_text == "two eggs"
    assert parsed.meal_type == "breakfast"


def test_extract_request_fields_partial_profile_yields_no_profile(monkeypatch):
    # Missing "age" — one field short of the required set.
    fields = {k: v for k, v in FULL_PROFILE_FIELDS.items() if k != "age"}
    raw = _raw(**fields, age=None)
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    parsed = agent_service.extract_request_fields("i weigh 75kg and am 178cm", llm=object())

    assert parsed.profile is None


def test_extract_request_fields_meal_text_without_type_defaults_to_snack(monkeypatch):
    raw = _raw(meal_text="a banana", meal_type=None)
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    parsed = agent_service.extract_request_fields("i ate a banana", llm=object())

    assert parsed.meal_text == "a banana"
    assert parsed.meal_type == "snack"


def test_extract_request_fields_nothing_present(monkeypatch):
    raw = _raw()
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    parsed = agent_service.extract_request_fields("hello there", llm=object())

    assert parsed.profile is None
    assert parsed.meal_text is None
    assert parsed.meal_type is None


def test_extract_request_fields_raises_valueerror_on_malformed_json(monkeypatch):
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM("not valid json{{{"))

    with pytest.raises(ValueError, match="Model returned invalid JSON"):
        agent_service.extract_request_fields("hello", llm=object())


def test_extract_request_fields_raises_valueerror_on_non_dict_json(monkeypatch):
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps([1, 2, 3])))

    with pytest.raises(ValueError, match="Model returned non-object JSON"):
        agent_service.extract_request_fields("hello", llm=object())


def test_extract_request_fields_retries_once_through_llm_call_then_succeeds(monkeypatch):
    """ADR-005 REQ-04: extract_request_fields now calls llm_call internally,
    which retries once on malformed JSON before raising. Before this
    migration there was no retry — a first malformed response raised
    immediately. This confirms the retry now works through the real
    extract_request_fields call site, not just llm_call in isolation
    (see test_llm_call.py for the isolated coverage)."""
    raw = _raw(meal_text="a banana", meal_type=None)
    monkeypatch.setattr(
        agent_service, "get_json_llm",
        lambda: SequenceLLM(["not valid json{{{", json.dumps(raw)]),
    )

    parsed = agent_service.extract_request_fields("i ate a banana", llm=object())

    assert parsed.meal_text == "a banana"
    assert parsed.meal_type == "snack"


def test_extract_request_fields_raises_valueerror_on_invalid_profile(monkeypatch):
    fields = {**FULL_PROFILE_FIELDS, "gender": "unknown"}  # invalid Literal value
    raw = _raw(**fields)
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    with pytest.raises(ValueError, match="Model produced an invalid profile"):
        agent_service.extract_request_fields("some message", llm=object())


# ---------------------------------------------------------------------------
# extract_request_fields -- ADR-008 multi-turn conversation_history
#
# Regression test for the exact reported bug: onboarding slot-filling forgot
# fields given in an earlier turn because extraction only ever saw the
# current message. Simulates two real turns end-to-end through the real
# extract_request_fields call site (not a mocked orchestrator), asserting
# turn 2's extraction carries ALL SIX profile fields forward, not just the
# three given in turn 2. Not covered by evals/ (parse_meal_text-only harness,
# single-message scoring) -- this pytest case is the permanent regression
# guard for this bug, per ADR-008 Action Item 7.
# ---------------------------------------------------------------------------

def test_extract_request_fields_conversation_history_carries_forward_earlier_turn_fields(monkeypatch):
    turn_1_message = "I weigh 75kg, I'm 178cm tall, and I'm 30 years old."
    turn_2_message = "I'm male, moderately active, and want to lose weight."

    # Turn 1: only weight/height/age given -- profile incomplete, missing
    # gender/activity_level/goal.
    turn_1_raw = _raw(weight_kg=75, height_cm=178, age=30, intent="set_profile")
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(turn_1_raw)))

    turn_1_parsed = agent_service.extract_request_fields(turn_1_message, llm=object())

    assert turn_1_parsed.profile is None
    assert set(turn_1_parsed.missing_profile_fields) == {"gender", "activity_level", "goal"}

    # Turn 2: only gender/activity_level/goal given in THIS message, but
    # conversation_history carries turn 1's message. A real LLM re-reads the
    # full transcript and returns all six fields combined -- this test's
    # FakeLLM stands in for that real re-extraction, asserting the CALLER
    # (extract_request_fields) correctly builds and feeds the full
    # transcript rather than dropping turn 1's message on the floor.
    turn_2_raw = _raw(**FULL_PROFILE_FIELDS, intent="set_profile")
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(turn_2_raw)))

    turn_2_parsed = agent_service.extract_request_fields(
        turn_2_message, llm=object(), conversation_history=[turn_1_message],
    )

    assert turn_2_parsed.profile is not None
    for field, expected_value in FULL_PROFILE_FIELDS.items():
        assert getattr(turn_2_parsed.profile, field) == expected_value
    assert turn_2_parsed.missing_profile_fields == []


def test_extract_request_fields_builds_conversation_block_with_all_messages(monkeypatch):
    """The prompt sent to the LLM must actually contain every prior message,
    not just the latest one -- otherwise a real model has no way to recover
    a field from an earlier turn regardless of instructions."""
    captured_prompts = []

    class CapturingLLM:
        def invoke(self, messages):
            captured_prompts.append(messages[0].content)
            return SimpleNamespace(content=json.dumps(_raw(**FULL_PROFILE_FIELDS, intent="set_profile")))

    monkeypatch.setattr(agent_service, "get_json_llm", lambda: CapturingLLM())

    agent_service.extract_request_fields(
        "I'm male, moderately active, and want to lose weight.",
        llm=object(),
        conversation_history=["I weigh 75kg, I'm 178cm tall, and I'm 30 years old."],
    )

    assert len(captured_prompts) == 1
    prompt = captured_prompts[0]
    assert "I weigh 75kg, I'm 178cm tall, and I'm 30 years old." in prompt
    assert "I'm male, moderately active, and want to lose weight." in prompt


# ---------------------------------------------------------------------------
# extract_request_fields -- Intent coercion (ADR-005 REQ-01/contract 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "raw_intent, expected_intent",
    [
        ("log_meal", Intent.LOG_MEAL),
        ("set_profile", Intent.SET_PROFILE),
        ("unknown", Intent.UNKNOWN),
    ],
)
def test_extract_request_fields_intent_recognized_value_maps_to_enum(monkeypatch, raw_intent, expected_intent):
    raw = _raw(intent=raw_intent)
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    parsed = agent_service.extract_request_fields("some message", llm=object())

    assert parsed.intent == expected_intent


def test_extract_request_fields_intent_missing_key_defaults_to_unknown(monkeypatch, caplog):
    # _raw()'s base dict has no "intent" key at all -- simulates a model
    # response that omits the field entirely (not even null).
    raw = _raw()
    assert "intent" not in raw
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    with caplog.at_level(logging.WARNING, logger="calai_backend.services.agent_service"):
        parsed = agent_service.extract_request_fields("hello there", llm=object())

    assert parsed.intent == Intent.UNKNOWN
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("coercing to UNKNOWN" in m for m in warning_messages)


def test_extract_request_fields_intent_null_value_defaults_to_unknown(monkeypatch, caplog):
    raw = _raw(intent=None)
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    with caplog.at_level(logging.WARNING, logger="calai_backend.services.agent_service"):
        parsed = agent_service.extract_request_fields("hello there", llm=object())

    assert parsed.intent == Intent.UNKNOWN
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("omitted intent" in m and "coercing to UNKNOWN" in m for m in warning_messages)


def test_extract_request_fields_intent_garbage_value_defaults_to_unknown_without_raising(monkeypatch, caplog):
    raw = _raw(intent="do_a_backflip")
    call_count = {"n": 0}

    class CountingLLM(FakeLLM):
        def invoke(self, messages):
            call_count["n"] += 1
            return super().invoke(messages)

    monkeypatch.setattr(agent_service, "get_json_llm", lambda: CountingLLM(json.dumps(raw)))

    with caplog.at_level(logging.WARNING, logger="calai_backend.services.agent_service"):
        parsed = agent_service.extract_request_fields("some gibberish message", llm=object())

    assert parsed.intent == Intent.UNKNOWN
    # An unrecognized-but-well-formed intent string is a soft-signal
    # coercion, not a schema-validation failure -- it must NOT trigger
    # llm_call's retry-then-raise path. Confirm exactly one LLM call.
    assert call_count["n"] == 1
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("unrecognized intent" in m and "do_a_backflip" in m for m in warning_messages)


def test_extract_request_fields_logs_classified_intent_and_raw_fields_at_debug(monkeypatch, caplog):
    raw = _raw(intent="log_meal", meal_text="two eggs")
    monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(json.dumps(raw)))

    with caplog.at_level(logging.DEBUG, logger="calai_backend.services.agent_service"):
        agent_service.extract_request_fields("i ate two eggs", llm=object())

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    combined = "\n".join(debug_messages)
    assert "log_meal" in combined
    # the raw extracted fields (e.g. the meal_text that drove the
    # classification) must appear alongside the classified intent, not just
    # the bare enum value.
    assert "two eggs" in combined


# ---------------------------------------------------------------------------
# compose_response
# ---------------------------------------------------------------------------

def _calc():
    return CalcResponse(bmr_kcal=1500.0, tdee_kcal=2200.0, calorie_goal_kcal=1800.0)


def _meal(items=None, total_kcal=250, meal_type="snack"):
    return {
        "items": items if items is not None else [{"name": "apple"}, {"name": "toast"}],
        "total_kcal": total_kcal,
        "meal_type": meal_type,
    }


def test_compose_response_calc_only():
    text = agent_service.compose_response(_calc(), None)

    assert "BMR is 1500 kcal/day" in text
    assert "TDEE is 2200 kcal/day" in text
    assert "calorie goal is 1800 kcal/day" in text
    assert "Logged" not in text


def test_compose_response_meal_only():
    text = agent_service.compose_response(None, _meal())

    assert "Logged snack: apple, toast (~250 kcal)." in text
    assert "BMR" not in text


def test_compose_response_both_present_joins_sentences():
    text = agent_service.compose_response(_calc(), _meal())

    assert "BMR is 1500" in text
    assert "Logged snack: apple, toast (~250 kcal)." in text


def test_compose_response_neither_present_returns_fallback_and_does_not_crash():
    text = agent_service.compose_response(None, None)

    assert "couldn't find" in text
    assert isinstance(text, str)


def test_compose_response_meal_with_empty_items_does_not_crash():
    text = agent_service.compose_response(None, _meal(items=[]))

    assert text == "Logged snack (~250 kcal)."


def test_compose_response_meal_with_none_total_kcal_degrades_gracefully():
    """Regression test for a fixed bug (reviewer fix-loop 1 finding 1).

    parse_meal returns whatever JSON the LLM emits (calai_backend/services/
    meal_parse_agent.py). The prompt asks for a numeric total_kcal but does
    not guarantee it — a real LLM can plausibly omit it, in which case
    meal.get("total_kcal") is None. compose_response must not crash on this;
    it should drop the "(~N kcal)" clause instead of raising TypeError on
    f"{total_kcal:.0f}".
    """
    text = agent_service.compose_response(None, _meal(total_kcal=None))

    assert text == "Logged snack: apple, toast."


def test_compose_response_meal_with_non_numeric_total_kcal_degrades_gracefully():
    """Same guard, non-numeric (e.g. string) total_kcal instead of None."""
    text = agent_service.compose_response(None, _meal(total_kcal="a lot"))

    assert text == "Logged snack: apple, toast."


# ---------------------------------------------------------------------------
# Orchestrator dispatch (_run_agent_orchestrator)
# ---------------------------------------------------------------------------

def _patch_steps(monkeypatch, *, profile=None, meal_text=None, meal_type=None):
    # ADR-005 REQ-01: ParsedRequest.intent is now required. This helper
    # constructs ParsedRequest directly (bypassing extract_request_fields),
    # so intent-classification is out of scope for these dispatch tests --
    # Intent.UNKNOWN is a neutral placeholder; _run_agent_orchestrator's
    # dispatch logic is purely presence-based on profile/meal_text and never
    # reads .intent (see agent_service.py), so this value doesn't affect
    # what these tests assert.
    parsed = ParsedRequest(profile=profile, meal_text=meal_text, meal_type=meal_type, intent=Intent.UNKNOWN)
    calls = {"extract": [], "calc_pipeline": [], "parse_meal": [], "compose": []}

    def fake_extract(message, llm):
        calls["extract"].append((message, llm))
        return parsed

    def fake_calc_pipeline(profile_arg):
        calls["calc_pipeline"].append(profile_arg)
        return _calc()

    def fake_parse_meal(meal_text_arg, meal_type_arg):
        calls["parse_meal"].append((meal_text_arg, meal_type_arg))
        return _meal()

    def fake_compose(calc, meal):
        calls["compose"].append((calc, meal))
        return "composed response"

    monkeypatch.setattr(agent_service, "extract_request_fields", fake_extract)
    monkeypatch.setattr(agent_service, "run_calc_pipeline", fake_calc_pipeline)
    monkeypatch.setattr(agent_service, "parse_meal", fake_parse_meal)
    monkeypatch.setattr(agent_service, "compose_response", fake_compose)
    return calls


def test_orchestrator_profile_and_meal_runs_both_steps(monkeypatch):
    calls = _patch_steps(
        monkeypatch,
        profile=CalcRequest(**FULL_PROFILE_FIELDS),
        meal_text="two eggs",
        meal_type="breakfast",
    )

    result = agent_service._run_agent_orchestrator("msg", llm=object())

    assert len(calls["calc_pipeline"]) == 1
    # ADR-005 Known Limitations #2 (eval-parity gap fix): parse_meal now gets
    # the raw orchestrator `message` argument, not the LLM-extracted/reworded
    # parsed_request.meal_text — closes the gap where production's input to
    # parse_meal diverged from what evals/run_eval.py scores against.
    assert calls["parse_meal"] == [("msg", "breakfast")]
    assert len(calls["compose"]) == 1
    assert calls["compose"][0][0] is not None  # calc
    assert calls["compose"][0][1] is not None  # meal
    assert result == AgentResponse(response="composed response", iterations_used=2)


def test_orchestrator_profile_only_runs_calc_pipeline_only(monkeypatch):
    calls = _patch_steps(monkeypatch, profile=CalcRequest(**FULL_PROFILE_FIELDS))

    result = agent_service._run_agent_orchestrator("msg", llm=object())

    assert len(calls["calc_pipeline"]) == 1
    assert calls["parse_meal"] == []
    assert calls["compose"][0][0] is not None
    assert calls["compose"][0][1] is None
    assert result.iterations_used == 1


def test_orchestrator_meal_only_runs_parse_meal_only(monkeypatch):
    calls = _patch_steps(monkeypatch, meal_text="a banana", meal_type="snack")

    result = agent_service._run_agent_orchestrator("msg", llm=object())

    assert calls["calc_pipeline"] == []
    # ADR-005 Known Limitations #2: raw message passed through, not the
    # extracted meal_text — see comment in the profile+meal test above.
    assert calls["parse_meal"] == [("msg", "snack")]
    assert calls["compose"][0][0] is None
    assert calls["compose"][0][1] is not None
    assert result.iterations_used == 1


def test_orchestrator_neither_present_runs_no_steps(monkeypatch):
    calls = _patch_steps(monkeypatch)

    result = agent_service._run_agent_orchestrator("msg", llm=object())

    assert calls["calc_pipeline"] == []
    assert calls["parse_meal"] == []
    assert calls["compose"] == [(None, None)]
    assert result.iterations_used == 0


def test_orchestrator_meal_text_present_with_no_meal_type_defaults_to_snack(monkeypatch):
    calls = _patch_steps(monkeypatch, meal_text="a banana", meal_type=None)

    agent_service._run_agent_orchestrator("msg", llm=object())

    # ADR-005 Known Limitations #2: raw message passed through, not the
    # extracted meal_text.
    assert calls["parse_meal"] == [("msg", "snack")]


# ---------------------------------------------------------------------------
# Raw-message pass-through logging (ADR-005 Known Limitations #2 /
# eval-parity gap fix) -- per the phased plan's per-phase logging-assertion
# rule, this confirms the raw-message-instead-of-extracted-meal_text
# decision is visible at DEBUG, not just implemented silently.
# ---------------------------------------------------------------------------

def test_orchestrator_logs_raw_message_skip_decision_at_debug(monkeypatch, caplog):
    """When meal_text is present, _run_agent_orchestrator must log a DEBUG
    line naming both the classified Intent value and the fact that it's
    using the raw message (not the extracted meal_text) for parse_meal --
    the exact decision that closes ADR-005 Known Limitations #2."""
    parsed = ParsedRequest(profile=None, meal_text="two eggs", meal_type="breakfast", intent=Intent.LOG_MEAL)
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)
    monkeypatch.setattr(agent_service, "run_calc_pipeline", lambda profile_arg: _calc())
    monkeypatch.setattr(agent_service, "parse_meal", lambda meal_text_arg, meal_type_arg: _meal())
    monkeypatch.setattr(agent_service, "compose_response", lambda calc, meal: "composed response")

    with caplog.at_level(logging.DEBUG, logger="calai_backend.services.agent_service"):
        agent_service._run_agent_orchestrator("i ate two eggs", llm=object())

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    combined = "\n".join(debug_messages)
    assert "log_meal" in combined
    assert "raw message" in combined
    assert "meal_text" in combined


def test_orchestrator_does_not_log_raw_message_skip_decision_when_no_meal_text(monkeypatch, caplog):
    """Negative case: with no meal_text present, parse_meal never runs, so
    the raw-message-skip DEBUG line must not fire either."""
    parsed = ParsedRequest(
        profile=CalcRequest(**FULL_PROFILE_FIELDS), meal_text=None, meal_type=None, intent=Intent.SET_PROFILE,
    )
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)
    monkeypatch.setattr(agent_service, "run_calc_pipeline", lambda profile_arg: _calc())
    monkeypatch.setattr(agent_service, "compose_response", lambda calc, meal: "composed response")

    with caplog.at_level(logging.DEBUG, logger="calai_backend.services.agent_service"):
        agent_service._run_agent_orchestrator("i weigh 75kg...", llm=object())

    debug_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.DEBUG]
    combined = "\n".join(debug_messages)
    assert "raw message" not in combined


# ---------------------------------------------------------------------------
# Orchestrator error translation (reviewer fix-loop 1 finding 2)
# ---------------------------------------------------------------------------

def test_orchestrator_translates_connect_error_to_503(monkeypatch):
    def raise_connect_error(message, llm):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(agent_service, "extract_request_fields", raise_connect_error)

    with pytest.raises(HTTPException) as exc_info:
        agent_service._run_agent_orchestrator("msg", llm=object())

    assert exc_info.value.status_code == 503


def test_orchestrator_translates_timeout_to_504(monkeypatch):
    def raise_timeout(message, llm):
        raise httpx.TimeoutException("boom")

    monkeypatch.setattr(agent_service, "extract_request_fields", raise_timeout)

    with pytest.raises(HTTPException) as exc_info:
        agent_service._run_agent_orchestrator("msg", llm=object())

    assert exc_info.value.status_code == 504


def test_orchestrator_translates_valueerror_from_parse_meal_to_422(monkeypatch):
    _patch_steps(monkeypatch, meal_text="a banana", meal_type="snack")

    def raise_value_error(meal_text_arg, meal_type_arg):
        raise ValueError("Model returned invalid JSON")

    monkeypatch.setattr(agent_service, "parse_meal", raise_value_error)

    with pytest.raises(HTTPException) as exc_info:
        agent_service._run_agent_orchestrator("msg", llm=object())

    assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# run_agent dispatch flag (USE_ORCHESTRATOR)
# ---------------------------------------------------------------------------

def test_run_agent_dispatches_to_orchestrator_when_flag_true(monkeypatch):
    monkeypatch.setattr(agent_service, "USE_ORCHESTRATOR", True)
    sentinel = AgentResponse(response="from orchestrator", iterations_used=1)
    called = {}

    def fake_orchestrator(message, llm, profile=None, trigger="message", conversation_history=None):
        called["orchestrator"] = (message, llm)
        return sentinel

    def fake_react_loop(message, llm):
        called["react_loop"] = (message, llm)
        raise AssertionError("react loop should not be called when flag is True")

    monkeypatch.setattr(agent_service, "_run_agent_orchestrator", fake_orchestrator)
    monkeypatch.setattr(agent_service, "_run_agent_react_loop", fake_react_loop)

    result = agent_service.run_agent("hi", llm=object())

    assert result is sentinel
    assert "orchestrator" in called
    assert "react_loop" not in called


# ---------------------------------------------------------------------------
# _run_agent_react_loop tool-call dispatch -- Harmony tool-name leak fix
# (openai/gpt-oss-20b via NVIDIA NIM intermittently leaks a trailing
# "<|channel|>..." tag onto ai_message.tool_calls[i]["name"], e.g.
# "calculate_calorie_goal<|channel|>commentary" instead of
# "calculate_calorie_goal", which broke tools_dict.get(tool_name) with a
# 500 "Unknown tool" error). No real LLM/network calls -- get_llm(tools=...)
# is faked with a small stand-in whose .invoke() returns canned
# AIMessage-shaped SimpleNamespace objects, same faking style as FakeLLM
# above. The real tool functions from tools/registry.py are exercised
# as-is (not mocked) so dispatch success is verified end-to-end past the
# name lookup.
# ---------------------------------------------------------------------------

class FakeToolCallLLM:
    """Returns one canned AIMessage-shaped response per `.invoke()` call, in
    order. The final response must have empty tool_calls so the loop exits
    cleanly with a final answer instead of hitting MAX_STEPS."""

    def __init__(self, responses):
        self._responses = list(responses)

    def invoke(self, messages):
        return self._responses.pop(0)


def _ai_message(tool_calls, content=""):
    return SimpleNamespace(content=content, tool_calls=tool_calls)


_FINAL_ANSWER = _ai_message([], content="done")


def test_react_loop_dispatches_harmony_leaked_tool_name_correctly(monkeypatch, caplog):
    """Bug repro: a leaked Harmony channel tag on the tool name must still
    dispatch to the real tool (calculate_bmr), not raise 'Unknown tool'."""
    leaked_call = {
        "name": "calculate_bmr<|channel|>commentary",
        "args": {"weight_kg": 75, "height_cm": 178, "age": 30, "gender": "male"},
        "id": "call_1",
    }
    fake_llm = FakeToolCallLLM([_ai_message([leaked_call]), _FINAL_ANSWER])
    monkeypatch.setattr(agent_service, "get_llm", lambda tools: fake_llm)

    with caplog.at_level(logging.WARNING, logger="calai_backend.services.agent_service"):
        result = agent_service._run_agent_react_loop("some message", llm=None)

    assert result == AgentResponse(response="done", iterations_used=2)
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any(
        "sanitized Harmony-format tool name leak" in m
        and "calculate_bmr<|channel|>commentary" in m
        for m in warning_messages
    )


def test_react_loop_clean_tool_name_dispatches_unaffected(monkeypatch, caplog):
    """A clean, uncorrupted tool name must dispatch normally, and the
    sanitization warning path must NOT fire -- a future regression that
    starts corrupting all names (or always taking the sanitize branch)
    would otherwise go unnoticed."""
    clean_call = {
        "name": "calculate_tdee",
        "args": {"bmr_kcal": 1500.0, "activity_level": "moderately_active"},
        "id": "call_1",
    }
    fake_llm = FakeToolCallLLM([_ai_message([clean_call]), _FINAL_ANSWER])
    monkeypatch.setattr(agent_service, "get_llm", lambda tools: fake_llm)

    with caplog.at_level(logging.WARNING, logger="calai_backend.services.agent_service"):
        result = agent_service._run_agent_react_loop("some message", llm=None)

    assert result == AgentResponse(response="done", iterations_used=2)
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert not any("sanitized Harmony-format tool name leak" in m for m in warning_messages)


def test_react_loop_corruption_leaving_empty_name_falls_through_to_unknown_tool_error(monkeypatch):
    """Edge case: if the Harmony marker is at position 0 (nothing before it),
    sanitizing yields an empty string. This must NOT silently match some
    tool -- it must fall through to the existing 'Unknown tool' 500 error."""
    empty_prefix_call = {
        "name": "<|channel|>commentary",
        "args": {},
        "id": "call_1",
    }
    fake_llm = FakeToolCallLLM([_ai_message([empty_prefix_call])])
    monkeypatch.setattr(agent_service, "get_llm", lambda tools: fake_llm)

    with pytest.raises(HTTPException) as exc_info:
        agent_service._run_agent_react_loop("some message", llm=None)

    assert exc_info.value.status_code == 500
    assert "Unknown tool" in exc_info.value.detail


# ---------------------------------------------------------------------------
# ADR-007 Action Item 4 -- message_type dispatch + exactly-one-payload
# invariant, one test per branch, plus the failure-degradation path (Action
# Item 7) and a byte-for-byte regression guard on the pre-existing plain-INFO
# default. No real LLM/pipeline calls -- extract_request_fields/
# run_calc_pipeline are monkeypatched consistently with _patch_steps above.
# ---------------------------------------------------------------------------

def _assert_only_payload(result, field_name):
    """Assert exactly one of the four AgentResponse payload fields is
    non-None, and it's `field_name`."""
    payload_fields = ("slot_fill", "profile_confirmation", "recommendation", "weekly_checkin")
    for f in payload_fields:
        value = getattr(result, f)
        if f == field_name:
            assert value is not None, f"expected {f} to be populated"
        else:
            assert value is None, f"expected {f} to be None, got {value!r}"


def test_orchestrator_weekly_checkin_trigger_short_circuits(monkeypatch):
    """Bug/behavior: trigger='weekly_checkin' must skip extraction entirely
    (ignores `message`) and return message_type=WEEKLY_CHECKIN with
    last_weight_kg sourced from `profile.weight_kg`."""
    def fail_if_called(message, llm):
        raise AssertionError("extract_request_fields must not be called on weekly_checkin trigger")

    monkeypatch.setattr(agent_service, "extract_request_fields", fail_if_called)
    profile = CalcRequest(**FULL_PROFILE_FIELDS)

    result = agent_service._run_agent_orchestrator(
        "this text is ignored", llm=object(), profile=profile, trigger="weekly_checkin",
    )

    assert result.message_type == AgentMessageType.WEEKLY_CHECKIN
    _assert_only_payload(result, "weekly_checkin")
    assert result.weekly_checkin.last_weight_kg == profile.weight_kg
    assert result.iterations_used == 0


def test_orchestrator_weekly_checkin_without_profile_has_none_last_weight(monkeypatch):
    def fail_if_called(message, llm):
        raise AssertionError("extract_request_fields must not be called on weekly_checkin trigger")

    monkeypatch.setattr(agent_service, "extract_request_fields", fail_if_called)

    result = agent_service._run_agent_orchestrator(
        "ignored", llm=object(), profile=None, trigger="weekly_checkin",
    )

    assert result.message_type == AgentMessageType.WEEKLY_CHECKIN
    assert result.weekly_checkin.last_weight_kg is None


def test_orchestrator_profile_confirmation_when_set_profile_intent_complete(monkeypatch):
    profile = CalcRequest(**FULL_PROFILE_FIELDS)
    parsed = ParsedRequest(profile=profile, meal_text=None, meal_type=None, intent=Intent.SET_PROFILE)
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)
    monkeypatch.setattr(agent_service, "run_calc_pipeline", lambda p: _calc())

    result = agent_service._run_agent_orchestrator("i weigh 75kg...", llm=object())

    assert result.message_type == AgentMessageType.PROFILE_CONFIRMATION
    _assert_only_payload(result, "profile_confirmation")
    assert result.profile_confirmation.profile == profile
    assert result.profile_confirmation.preview == _calc()


def test_orchestrator_profile_confirmation_preview_matches_real_calc_pipeline(monkeypatch):
    """ADR-007 review requirement: ProfileConfirmationPayload.preview must not
    reimplement the BMR/TDEE/goal math -- it must equal whatever the real
    run_calc_pipeline (the same function backing /api/calculate) returns for
    the identical profile. This test does NOT mock run_calc_pipeline, so it
    calls the real deterministic pipeline both inside the orchestrator and
    independently here, and compares the two results instead of hardcoding
    a number that could silently drift."""
    profile = CalcRequest(**FULL_PROFILE_FIELDS)
    parsed = ParsedRequest(profile=profile, meal_text=None, meal_type=None, intent=Intent.SET_PROFILE)
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)

    result = agent_service._run_agent_orchestrator("i weigh 75kg...", llm=object())

    expected = run_calc_pipeline(profile)
    assert result.message_type == AgentMessageType.PROFILE_CONFIRMATION
    assert result.profile_confirmation.preview == expected


def test_orchestrator_slot_fill_question_when_set_profile_intent_incomplete(monkeypatch):
    parsed = ParsedRequest(profile=None, meal_text=None, meal_type=None, intent=Intent.SET_PROFILE)
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)

    result = agent_service._run_agent_orchestrator("i weigh 75kg", llm=object())

    assert result.message_type == AgentMessageType.SLOT_FILL_QUESTION
    _assert_only_payload(result, "slot_fill")
    assert set(result.slot_fill.missing) == set(agent_service._REQUIRED_PROFILE_FIELD_NAMES)


def test_orchestrator_recommendation_when_client_profile_and_keyword_present(monkeypatch):
    client_profile = CalcRequest(**FULL_PROFILE_FIELDS)
    parsed = ParsedRequest(profile=None, meal_text=None, meal_type=None, intent=Intent.UNKNOWN)
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)
    monkeypatch.setattr(agent_service, "run_calc_pipeline", lambda p: _calc())

    result = agent_service._run_agent_orchestrator(
        "should I adjust my goal?", llm=object(), profile=client_profile,
    )

    assert result.message_type == AgentMessageType.RECOMMENDATION
    _assert_only_payload(result, "recommendation")
    assert result.recommendation.calorie_goal_kcal == _calc().calorie_goal_kcal
    assert result.recommendation.tdee_kcal == _calc().tdee_kcal
    assert result.recommendation.bmr_kcal == _calc().bmr_kcal


def test_orchestrator_info_default_unchanged_regression(monkeypatch):
    """Regression guard: today's default plain-INFO path (no SET_PROFILE
    intent, no recommendation keywords, trigger='message') must produce
    exactly the same AgentResponse shape as before ADR-007 -- message_type
    INFO and all four new payload fields None."""
    calls = _patch_steps(
        monkeypatch,
        profile=CalcRequest(**FULL_PROFILE_FIELDS),
        meal_text="two eggs",
        meal_type="breakfast",
    )

    result = agent_service._run_agent_orchestrator("msg", llm=object())

    assert result == AgentResponse(
        response="composed response",
        iterations_used=2,
        message_type=AgentMessageType.INFO,
        slot_fill=None,
        profile_confirmation=None,
        recommendation=None,
        weekly_checkin=None,
    )


def test_orchestrator_profile_confirmation_degrades_to_info_on_calc_pipeline_valueerror(monkeypatch):
    """ADR-007 Action Item 7 failure-degradation path: a ValueError raised
    while composing the profile_confirmation payload must degrade to
    message_type=INFO with profile_confirmation=None and a plain-language
    response, never propagate as an unhandled exception / 500."""
    profile = CalcRequest(**FULL_PROFILE_FIELDS)
    parsed = ParsedRequest(profile=profile, meal_text=None, meal_type=None, intent=Intent.SET_PROFILE)
    monkeypatch.setattr(agent_service, "extract_request_fields", lambda message, llm: parsed)

    def raise_value_error(p):
        raise ValueError("boom: implausible TDEE")

    monkeypatch.setattr(agent_service, "run_calc_pipeline", raise_value_error)

    result = agent_service._run_agent_orchestrator("i weigh 75kg...", llm=object())

    assert result.message_type == AgentMessageType.INFO
    assert result.profile_confirmation is None
    _assert_only_payload(result, None)  # every payload field is None
    assert "couldn't confirm" in result.response


def test_run_agent_dispatches_to_react_loop_when_flag_false(monkeypatch):
    monkeypatch.setattr(agent_service, "USE_ORCHESTRATOR", False)
    sentinel = AgentResponse(response="from react loop", iterations_used=3)
    called = {}

    def fake_orchestrator(message, llm):
        called["orchestrator"] = (message, llm)
        raise AssertionError("orchestrator should not be called when flag is False")

    def fake_react_loop(message, llm):
        called["react_loop"] = (message, llm)
        return sentinel

    monkeypatch.setattr(agent_service, "_run_agent_orchestrator", fake_orchestrator)
    monkeypatch.setattr(agent_service, "_run_agent_react_loop", fake_react_loop)

    result = agent_service.run_agent("hi", llm=object())

    assert result is sentinel
    assert "react_loop" in called
    assert "orchestrator" not in called
