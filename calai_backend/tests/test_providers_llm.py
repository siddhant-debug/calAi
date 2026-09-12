"""Tests for calai_backend/providers/llm.py (ADR-006: NVIDIA NIM migration).

No real network calls — `ChatNVIDIA` is monkeypatched at the module level
with a fake client that records the order operations happen in, following
this repo's FakeLLM/monkeypatch convention (see test_agent_service.py,
test_meal_parse_agent.py).

Covers what the migration actually introduced and nothing already covered
by the 93 pre-existing tests (which mock get_json_llm/get_llm at the
call-site level and never exercise provider internals):

1. get_llm(tools=[...]) binds tools on the *raw* client before retry/
   fallback wrapping — the one bug-prone ordering constraint in this module.
2. get_llm() / get_json_llm() build a client chain sized to
   len(config.LLM_MODELS), wired as primary.with_fallbacks(rest).
3. Fallback actually falls through to the next model when the primary
   raises (black-box, at the client level — not exercising real LangChain
   retry/fallback internals).
"""
import pytest

from calai_backend.providers import llm as llm_module


# ---------------------------------------------------------------------------
# Fake ChatNVIDIA client chain — mirrors the shape of the real
# ChatNVIDIA / RunnableRetry / RunnableWithFallbacks objects just enough to
# exercise providers/llm.py's wiring. Records every operation so tests can
# assert on *order*, not just the end shape.
# ---------------------------------------------------------------------------

class FakeChatNVIDIA:
    """Stand-in for a raw ChatNVIDIA client. Only this class exposes
    bind_tools() — mirroring the real constraint that RunnableRetry /
    RunnableWithFallbacks do not."""

    def __init__(self, model, api_key=None, temperature=0, call_log=None, fail_models=None, **kwargs):
        self.model = model
        self.tools = None
        self.call_log = call_log if call_log is not None else []
        self.fail_models = fail_models or set()
        self.call_log.append(("raw_created", model))

    def bind_tools(self, tools):
        self.tools = tools
        self.call_log.append(("bind_tools", self.model))
        return self

    def with_retry(self, **kwargs):
        self.call_log.append(("with_retry", self.model))
        return FakeRetried(self)

    def invoke(self, *args, **kwargs):
        if self.model in self.fail_models:
            raise RuntimeError(f"{self.model} unavailable")
        return f"response-from-{self.model}"


class FakeRetried:
    """Stand-in for RunnableRetry — no .bind_tools(), only .with_fallbacks()
    and passthrough .invoke()."""

    def __init__(self, inner: FakeChatNVIDIA):
        self.inner = inner

    def with_fallbacks(self, fallbacks):
        self.inner.call_log.append(("with_fallbacks", self.inner.model))
        return FakeChain(self, list(fallbacks))

    def invoke(self, *args, **kwargs):
        return self.inner.invoke(*args, **kwargs)


class FakeChain:
    """Stand-in for RunnableWithFallbacks — primary first, then each
    fallback in order, matching real LangChain fallback semantics closely
    enough for a black-box wiring test."""

    def __init__(self, primary: FakeRetried, fallbacks: list[FakeRetried]):
        self.primary = primary
        self.fallbacks = fallbacks

    def invoke(self, *args, **kwargs):
        for candidate in [self.primary, *self.fallbacks]:
            try:
                return candidate.invoke(*args, **kwargs)
            except RuntimeError:
                continue
        raise RuntimeError("all models in fallback chain failed")


@pytest.fixture
def call_log():
    return []


@pytest.fixture
def patch_chat_nvidia(monkeypatch, call_log):
    """Patches ChatNVIDIA to FakeChatNVIDIA, threading a shared call_log and
    optional fail_models set through every constructed client."""

    def _patch(fail_models=None):
        def factory(model, **kwargs):
            return FakeChatNVIDIA(model, call_log=call_log, fail_models=fail_models or set(), **kwargs)

        monkeypatch.setattr(llm_module, "ChatNVIDIA", factory)
        return call_log

    return _patch


# ---------------------------------------------------------------------------
# 1. get_llm(tools=[...]) — bind_tools ordering constraint
# ---------------------------------------------------------------------------

def test_get_llm_binds_tools_before_retry_and_fallback_wrapping(patch_chat_nvidia):
    call_log = patch_chat_nvidia()
    fake_tools = [object(), object()]

    result = llm_module.get_llm(tools=fake_tools)

    # End-shape check: the returned chain's primary ends up with tools bound.
    assert isinstance(result, FakeChain)
    assert result.primary.inner.tools == fake_tools

    # Order check (the actual regression this test guards): for the primary
    # model, bind_tools must appear strictly before with_retry, which must
    # appear strictly before with_fallbacks. If a future change reversed the
    # order (wrapping first, then trying .bind_tools() on the wrapped
    # RunnableRetry/RunnableWithFallbacks), this would either raise
    # AttributeError in the real code or, in this fake, show bind_tools
    # missing/out of order.
    primary_model = llm_module.LLM_MODELS[0]
    primary_ops = [op for op, model in call_log if model == primary_model]
    assert primary_ops.index("bind_tools") < primary_ops.index("with_retry")
    assert primary_ops.index("with_retry") < primary_ops.index("with_fallbacks")

    # Every model in the chain (not just the primary) got tools bound before
    # wrapping — get_llm applies bind_tools to each raw client in the list.
    for model in llm_module.LLM_MODELS:
        ops = [op for op, m in call_log if m == model]
        assert "bind_tools" in ops
        assert ops.index("bind_tools") < ops.index("with_retry")


def test_get_llm_without_tools_never_calls_bind_tools(patch_chat_nvidia):
    call_log = patch_chat_nvidia()

    llm_module.get_llm()

    assert all(op != "bind_tools" for op, _ in call_log)


def test_get_json_llm_never_calls_bind_tools(patch_chat_nvidia):
    call_log = patch_chat_nvidia()

    llm_module.get_json_llm()

    assert all(op != "bind_tools" for op, _ in call_log)


# ---------------------------------------------------------------------------
# 2. Client chain sizing / wiring — primary + N-1 fallbacks
# ---------------------------------------------------------------------------

def test_get_llm_builds_chain_sized_to_llm_models(patch_chat_nvidia):
    patch_chat_nvidia()

    result = llm_module.get_llm()

    assert isinstance(result, FakeChain)
    assert len(result.fallbacks) == len(llm_module.LLM_MODELS) - 1
    assert result.primary.inner.model == llm_module.LLM_MODELS[0]
    assert [f.inner.model for f in result.fallbacks] == llm_module.LLM_MODELS[1:]


def test_get_json_llm_builds_chain_sized_to_llm_models(patch_chat_nvidia):
    patch_chat_nvidia()

    result = llm_module.get_json_llm()

    assert isinstance(result, FakeChain)
    assert len(result.fallbacks) == len(llm_module.LLM_MODELS) - 1
    assert result.primary.inner.model == llm_module.LLM_MODELS[0]
    assert [f.inner.model for f in result.fallbacks] == llm_module.LLM_MODELS[1:]


def test_get_llm_and_get_json_llm_remain_zero_required_arg(patch_chat_nvidia):
    """ADR-006 hard constraint: both stay zero-required-arg callables
    returning a single BaseChatModel-shaped object (no tuple/list)."""
    patch_chat_nvidia()

    llm_result = llm_module.get_llm()
    json_result = llm_module.get_json_llm()

    assert not isinstance(llm_result, (list, tuple))
    assert not isinstance(json_result, (list, tuple))


# ---------------------------------------------------------------------------
# 3. Fallback behavior — primary raises, chain falls through
# ---------------------------------------------------------------------------

def test_get_llm_falls_through_to_next_model_when_primary_fails(patch_chat_nvidia):
    primary_model = llm_module.LLM_MODELS[0]
    patch_chat_nvidia(fail_models={primary_model})

    result = llm_module.get_llm()
    response = result.invoke("hi")

    second_model = llm_module.LLM_MODELS[1]
    assert response == f"response-from-{second_model}"


def test_get_json_llm_falls_through_to_next_model_when_primary_fails(patch_chat_nvidia):
    primary_model = llm_module.LLM_MODELS[0]
    patch_chat_nvidia(fail_models={primary_model})

    result = llm_module.get_json_llm()
    response = result.invoke("hi")

    second_model = llm_module.LLM_MODELS[1]
    assert response == f"response-from-{second_model}"


def test_get_llm_falls_through_multiple_failed_models(patch_chat_nvidia, monkeypatch):
    """Two models down in a row — chain must still reach the third.

    Uses a monkeypatched 3-model LLM_MODELS rather than the real production
    list: this test asserts a general property of the fallback-chain wiring
    (it keeps trying past more than one failure), not anything about how
    many models config.py currently ships. Production LLM_MODELS dropped to
    2 after 3 of the original 4 NIM models were found dead (410 Gone); that
    change is covered by config, not this test.
    """
    first, second, third = "fake/model-a", "fake/model-b", "fake/model-c"
    monkeypatch.setattr(llm_module, "LLM_MODELS", [first, second, third])
    patch_chat_nvidia(fail_models={first, second})

    result = llm_module.get_llm()
    response = result.invoke("hi")

    assert response == f"response-from-{third}"


def test_get_llm_raises_when_every_model_in_chain_fails(patch_chat_nvidia):
    patch_chat_nvidia(fail_models=set(llm_module.LLM_MODELS))

    result = llm_module.get_llm()

    with pytest.raises(RuntimeError):
        result.invoke("hi")
