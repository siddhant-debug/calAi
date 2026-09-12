"""ADR-006: chat LLM provider, NVIDIA NIM (ChatNVIDIA) with a
retry+fallback chain (see `config.LLM_MODELS` for current chain length and
membership — shrunk from the original 4 to 2 after 3 of the 4 were found
retired by NVIDIA post-migration). Replaces the old single-model ChatOllama
provider outright — no rollback flag (see ADR-006 Decision section).

Both public functions (`get_llm`, `get_json_llm`) remain zero-required-arg
callables returning a single `BaseChatModel`-shaped object — this is a hard
constraint, not a style preference, since existing tests monkeypatch
`get_json_llm` as a bare zero-arg callable (see ADR-006 Test impact).
"""
from langchain_core.language_models import BaseChatModel
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from calai_backend.config import LLM_MODELS, NVIDIA_API_KEY


def _raw_clients(**kwargs) -> list[BaseChatModel]:
    """One bare ChatNVIDIA per model in LLM_MODELS, in fallback order.

    kwargs (e.g. a future response_format) are applied identically to every
    model in the chain. These are unwrapped BaseChatModel instances — the
    only place in this module .bind_tools() is legal to call, since
    RunnableRetry/RunnableWithFallbacks (what _with_retry_and_fallback
    returns) are not BaseChatModel and have no .bind_tools().
    """
    return [
        ChatNVIDIA(model=m, api_key=NVIDIA_API_KEY, temperature=0, **kwargs)
        for m in LLM_MODELS
    ]


def _with_retry_and_fallback(clients: list[BaseChatModel]) -> BaseChatModel:
    """Each client gets its own retry policy (absorbs NIM free-tier 503s),
    then the whole chain is wired as primary.with_fallbacks([...rest])."""
    retried = [
        c.with_retry(stop_after_attempt=2, wait_exponential_jitter=True)
        for c in clients
    ]
    return retried[0].with_fallbacks(retried[1:])


def get_llm(tools: list | None = None) -> BaseChatModel:
    """Returns the retry+fallback-wrapped primary client.

    If `tools` is given, .bind_tools() is applied to each raw client BEFORE
    retry/fallback wrapping (ADR-006's ordering constraint: RunnableRetry /
    RunnableWithFallbacks are not BaseChatModel and have no .bind_tools()).
    Default `tools=None` preserves the pre-ADR-006 zero-arg call shape for
    any caller not binding tools.

    Used by the ReAct loop (agent_service.py::_run_agent_react_loop), which
    calls `get_llm(tools=tools)` directly rather than binding tools onto
    whatever the FastAPI route's DI handed it — the tool list is only known
    inside the ReAct loop, not at the route boundary.
    """
    clients = _raw_clients()
    if tools:
        clients = [c.bind_tools(tools) for c in clients]
    return _with_retry_and_fallback(clients)


def get_json_llm() -> BaseChatModel:
    """Returns retry+fallback-wrapped clients for best-effort JSON output.

    No response_format/constrained-decoding kwarg is bound — NIM has no
    provider-wide JSON-mode flag, and support is model-specific/unverified
    across all 4 LLM_MODELS. Relies on prompt-enforced JSON plus the
    existing downstream parse-retry logic (services/llm_call.py) — see
    ADR-006's JSON-mode decision.
    """
    return _with_retry_and_fallback(_raw_clients())
