"""Repo-wide pytest fixtures for calai_backend/tests.

`write_trace` (calai_backend/services/llm_call.py) appends TraceRecord JSON
lines to calai_backend/logs/traces/{date}.jsonl on the real filesystem. Any
test that exercises the real llm_call() code path (directly or via
agent_service.py / meal_parse_agent.py) would otherwise write production-
shaped trace data to disk as a side effect of running the suite.

This autouse fixture patches write_trace to a no-op by default for every
test in this directory. Tests that specifically want to assert on trace
emission (see test_llm_call.py) override this via their own monkeypatch.setattr
call on calai_backend.services.llm_call.write_trace within the test body,
which takes precedence over this fixture's patch for that test.
"""
import pytest

from calai_backend.services import llm_call as llm_call_module


@pytest.fixture(autouse=True)
def no_real_trace_writes(monkeypatch):
    monkeypatch.setattr(llm_call_module, "write_trace", lambda record: None)
