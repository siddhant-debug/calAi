"""Tests for services/llm_call.py (ADR-005 contract 5 / REQ-04).

No real LLM calls — a fake chat-model stub (matching the FakeLLM pattern
already used in test_agent_service.py / test_meal_parse_agent.py) supplies
canned `.invoke(...)` responses. Covers the exactly-one-retry-then-raise
policy, the TraceRecord emitted per invocation (contract 6 / REQ-05), and
the DEBUG/WARNING log emission required by ADR-005's Action Items 8-9.
"""
import logging
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from calai_backend.services import llm_call as llm_call_module
from calai_backend.services.llm_call import LLMCallResult, llm_call


class _Schema(BaseModel):
    foo: str


class SequenceLLM:
    """Fake chat model returning one canned response per `.invoke()` call,
    in order. Raises IndexError if invoked more times than responses
    supplied (a test bug, not product behavior, if that happens)."""

    def __init__(self, contents):
        self._contents = list(contents)
        self.invocations = 0

    def invoke(self, messages):
        self.invocations += 1
        content = self._contents.pop(0)
        return SimpleNamespace(content=content)


# no_real_trace_writes: the autouse fixture that used to live here is now
# provided repo-wide by calai_backend/tests/conftest.py. Tests below that
# specifically assert on trace emission override it via _patch_write_trace.


# ---------------------------------------------------------------------------
# Success / retry / failure paths
# ---------------------------------------------------------------------------

def test_llm_call_success_first_try_no_retry():
    llm = SequenceLLM(['{"foo": "bar"}'])

    result = llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert isinstance(result, LLMCallResult)
    assert result.retry_count == 0
    assert result.output.foo == "bar"
    assert llm.invocations == 1


def test_llm_call_retry_then_succeed():
    llm = SequenceLLM(["not valid json{{{", '{"foo": "bar"}'])

    result = llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert result.retry_count == 1
    assert result.output.foo == "bar"
    assert llm.invocations == 2


def test_llm_call_retry_then_fail_raises_valueerror():
    llm = SequenceLLM(["not valid json{{{", "still not valid json{{{"])

    with pytest.raises(ValueError):
        llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert llm.invocations == 2


def test_llm_call_schema_validation_failure_triggers_retry_then_raise():
    # Valid JSON both times, but missing the required "foo" field both
    # times — schema-validation failure, not a JSON-decode failure, must
    # follow the same retry-then-raise path.
    llm = SequenceLLM(['{"wrong_field": "x"}', '{"wrong_field": "y"}'])

    with pytest.raises(ValueError):
        llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert llm.invocations == 2


def test_llm_call_schema_validation_failure_then_valid_succeeds_with_retry():
    llm = SequenceLLM(['{"wrong_field": "x"}', '{"foo": "bar"}'])

    result = llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert result.retry_count == 1
    assert result.output.foo == "bar"


# ---------------------------------------------------------------------------
# TraceRecord emission
# ---------------------------------------------------------------------------

def _patch_write_trace(monkeypatch):
    captured = []
    monkeypatch.setattr(llm_call_module, "write_trace", lambda record: captured.append(record))
    return captured


def test_llm_call_emits_trace_record_on_success(monkeypatch):
    captured = _patch_write_trace(monkeypatch)
    llm = SequenceLLM(['{"foo": "bar"}'])

    llm_call(name="test_call", prompt="the prompt", schema=_Schema, llm=llm)

    assert len(captured) == 1
    record = captured[0]
    assert record.call_name == "test_call"
    assert record.prompt == "the prompt"
    assert record.raw_response == '{"foo": "bar"}'
    assert record.parsed_output == {"foo": "bar"}
    assert record.retry_count == 0
    assert record.outcome == "ok"
    assert record.latency_ms >= 0


def test_llm_call_emits_trace_record_with_retry_count_one_on_retry_success(monkeypatch):
    captured = _patch_write_trace(monkeypatch)
    llm = SequenceLLM(["not valid json{{{", '{"foo": "bar"}'])

    llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert len(captured) == 1
    assert captured[0].retry_count == 1
    assert captured[0].outcome == "ok"


def test_llm_call_emits_trace_record_with_outcome_error_on_final_failure(monkeypatch):
    captured = _patch_write_trace(monkeypatch)
    llm = SequenceLLM(["not valid json{{{", "still not valid json{{{"])

    with pytest.raises(ValueError):
        llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    assert len(captured) == 1
    assert captured[0].retry_count == 1
    assert captured[0].outcome == "error"


# ---------------------------------------------------------------------------
# Logging: DEBUG on every invocation, WARNING specifically on retry
# ---------------------------------------------------------------------------

def test_llm_call_logs_debug_on_success(caplog):
    caplog.set_level(logging.DEBUG, logger="calai_backend.services.llm_call")
    llm = SequenceLLM(['{"foo": "bar"}'])

    llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("llm_call ok" in r.getMessage() for r in debug_records)


def test_llm_call_logs_warning_when_retry_fires(caplog):
    caplog.set_level(logging.DEBUG, logger="calai_backend.services.llm_call")
    llm = SequenceLLM(["not valid json{{{", '{"foo": "bar"}'])

    llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any("llm_call retry" in r.getMessage() for r in warning_records)


def test_llm_call_no_warning_logged_when_no_retry_fires(caplog):
    caplog.set_level(logging.DEBUG, logger="calai_backend.services.llm_call")
    llm = SequenceLLM(['{"foo": "bar"}'])

    llm_call(name="test_call", prompt="p", schema=_Schema, llm=llm)

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning_records == []
