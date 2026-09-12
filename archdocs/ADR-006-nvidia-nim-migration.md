# ADR-006: Migrate Chat LLM Provider from Local Ollama to NVIDIA NIM

**Status:** Proposed — architecture only, no code changes yet
**Date:** 2026-09-11
**Deciders:** Siddhant Tomar
**Companions:** ADR-001 (system architecture — defines `providers/llm.py`'s role), ADR-003 (multiagent split — the `.bind_tools()` call site this migration must preserve, `agent_service.py:346`), ADR-004 (eval harness — its committed baseline is invalidated by this migration, see Consequences), ADR-005 (router/handler registry — currently blocked mid-flight on Ollama being unreachable in the sandbox; this migration removes that blocker as a side effect, but ADR-005's own execution remains out of scope here)

---

## Context

CalAI's entire chat LLM surface (`calai_backend/providers/llm.py`) is two functions, both hardcoded to a local Ollama server:

```python
def get_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0)

def get_json_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0, format="json")
```

This has three concrete costs today, not hypothetical future ones:

1. **The ADR-005 refactor is actively blocked by it.** Per `project_adr005_refactor_status.md`, the router/handler-registry work is stalled mid-flight because Ollama is unreachable in the current sandbox. Every LLM-dependent phase of that ADR — and any other backend work touching `extract_request_fields`, `parse_meal`, or the ReAct fallback — is stuck behind a single local process being reachable, with no fallback path when it isn't.
2. **Single point of failure, no redundancy.** `MODEL_NAME` names exactly one model on exactly one host. If that Ollama instance is down, slow, or the pulled model is wrong (CLAUDE.md already flags a live drift: config defaults to `qwen2.5:7b`, but only `qwen2.5:3b` is actually pulled) — there is no fallback, no retry-to-a-different-model, nothing. The system either works on the one model that happens to be running, or it doesn't work.
3. **Local-only means it doesn't run anywhere CalAI needs to eventually run.** A local Ollama dependency is fine for a laptop demo; it is not viable for a deployed backend (CI, a hosted eval run, a reviewer's machine that doesn't have the same models pulled). `SYSTEM-DESIGN-1000-USERS.md`'s premise of a real deployed service is undermined by a chat LLM provider that only works on one specific developer's machine with one specific model already downloaded.

**Why this matters for the project's stated goal:** the project's resume narrative already rests on treating the LLM surface as a first-class engineering concern (ADR-003's isolation of `MealParseAgent`, ADR-004's eval harness, ADR-005's `llm_call` retry/trace contract). All of that infrastructure currently sits on top of a provider with no redundancy and no portability. Moving to a hosted multi-model provider with a documented fallback chain is the natural next layer under that stack, not a new concern.

---

## Non-Goals

- This does **not** change any API contract Flutter consumes (`/api/agent`, `/api/parse-meal`, `/api/calculate` keep their existing request/response shapes). The swap is entirely internal to `calai_backend/providers/llm.py` and its call sites.
- This does not change `MAX_STEPS`, `USE_ORCHESTRATOR`, or any orchestration/routing logic from ADR-003/ADR-005. Those flags and the decisions they gate are unaffected — this ADR only changes *which model answers*, not *when a model is called*.
- This does not implement or resume ADR-005's execution. Removing its Ollama-reachability blocker is a welcome side effect, not this ADR's purpose.
- This does not attempt to fix confidence calibration (39.6%, ADR-004's known limitation) or any meal-parsing accuracy issue. A fresh accuracy baseline is a required *consequence* of this migration (see below), not a goal it sets out to improve.
- This does not add a dual-provider runtime switch (see Decision — this is a deliberate one-way cut, unlike ADR-003's `USE_ORCHESTRATOR` pattern).

---

## Decision

Replace `ChatOllama` with `ChatNVIDIA` (NVIDIA NIM, `langchain-nvidia-ai-endpoints`) as the sole chat LLM provider, with a 4-model fallback chain and per-model retry, mirroring the pattern already proven in the `GOT_RAG` sibling project. **No rollback flag** — `ChatOllama`, `OLLAMA_BASE_URL`, and `MODEL_NAME` are removed from the chat path entirely, not kept behind a switch.

### Config surface (`calai_backend/config.py`)

```python
NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")
LLM_MODELS: list[str] = [
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",  # primary
    "meta/llama-3.1-8b-instruct",
    "mistralai/mixtral-8x7b-instruct-v0.1",
    "nvidia/llama-3.1-nemotron-nano-8b-v1",
]
```

Removed entirely: `OLLAMA_BASE_URL`, `MODEL_NAME`. Unaffected, left exactly as-is: `MAX_STEPS`, `USE_ORCHESTRATOR` (and, once ADR-005 resumes, `REACT_FALLBACK_MAX_STEPS`).

**`LLM_MODELS` model IDs must be verified live on build.nvidia.com before shipping** — this is the same caveat GOT_RAG's own `config.py` carries for this exact list; NIM's catalog changes, and a stale model ID fails at call time, not at config-load time.

### `providers/llm.py` redesign

Adopt GOT_RAG's three-function pattern, adapted to CalAI's two call sites:

```python
from langchain_core.language_models import BaseChatModel
from langchain_nvidia_ai_endpoints import ChatNVIDIA

from calai_backend.config import LLM_MODELS, NVIDIA_API_KEY


def _raw_clients(**kwargs) -> list[BaseChatModel]:
    """One bare ChatNVIDIA per model in LLM_MODELS, in fallback order.
    kwargs (e.g. response_format) are applied identically to every model
    in the chain."""
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


def get_llm() -> BaseChatModel:
    """Returns the raw (untyped-BaseChatModel) primary client with retry+fallback.
    Used at the /agent route (api/routes.py Depends(get_llm)) where the caller
    still needs .bind_tools() — see the ordering note below."""
    return _with_retry_and_fallback(_raw_clients())


def get_json_llm() -> BaseChatModel:
    """Returns retry+fallback-wrapped clients configured for best-effort JSON
    output. See 'JSON-mode decision' below for what **kwargs this applies."""
    return _with_retry_and_fallback(_raw_clients())
```

Both remain **zero-argument callables returning a single `BaseChatModel`-shaped object** — this is a hard constraint, not a style preference (see Test impact below).

### `.bind_tools()` ordering constraint

`RunnableRetry` and `RunnableWithFallbacks` are not `BaseChatModel` subclasses and have no `.bind_tools()` method. The current `/agent` route pattern —

```python
# api/routes.py
def agent(req: AgentRequest, llm: BaseChatModel = Depends(get_llm)) -> AgentResponse: ...
# agent_service.py:346 (ReAct loop)
llm_with_tools = llm.bind_tools(tools)
```

— calls `.bind_tools()` on whatever `get_llm()` returns, **after** DI has already handed it the fully-wrapped object. Under the naive redesign above, that breaks: `get_llm()` returns a `RunnableWithFallbacks`, which has no `.bind_tools()`.

**Resolution:** `.bind_tools()` must move to *before* retry/fallback wrapping, mirroring GOT_RAG's documented ordering constraint. Restructure `get_llm()` to accept the tools at construction time rather than exposing a bindable object downstream:

```python
def get_llm(tools: list | None = None) -> BaseChatModel:
    """If tools is given, .bind_tools() is applied to each raw client
    BEFORE retry/fallback wrapping (RunnableRetry/RunnableWithFallbacks
    are not BaseChatModel and have no .bind_tools())."""
    clients = _raw_clients()
    if tools:
        clients = [c.bind_tools(tools) for c in clients]
    return _with_retry_and_fallback(clients)
```

This changes `get_llm`'s signature (optional `tools` param, default `None` preserves today's zero-arg call shape for any caller not binding tools) and requires one call-site change: `agent_service.py:346`'s `_run_agent_react_loop` (and, once ADR-005 lands, `handlers/react_fallback.py`) must call `get_llm(tools=tools)` instead of `get_llm().bind_tools(tools)`. `api/routes.py`'s `Depends(get_llm)` — which doesn't know the tool list at DI time — is replaced by injecting the raw callable/model and letting `_run_agent_react_loop` perform the tools-aware construction itself, since the tool list is only known inside the ReAct loop, not at the FastAPI route boundary. This is a deliberate, scoped signature change to `get_llm`, not a silent contract break — `ai-engineer` should treat "does anything else call `get_llm()` expecting a bindable `BaseChatModel`" as a dedicated grep pass during implementation (Action Item 5).

### JSON-mode decision

`ChatOllama`'s `format="json"` has no universal NIM equivalent — NVIDIA NIM has no provider-wide JSON-mode flag; support for `response_format={"type": "json_object"}`-style constrained decoding is model-specific and not guaranteed across all 4 models in `LLM_MODELS`.

**Decision: prompt-enforced JSON, relying on the existing downstream parse-retry logic.** `get_json_llm()` does **not** attempt to bind a `response_format` kwarg. Both current call sites (`meal_parse_agent.py:72`, `agent_service.py:120`) already treat JSON-mode output as best-effort — malformed output already triggers existing retry/error handling (and, once ADR-005 lands, this exact responsibility formalizes into `llm_call`'s one-retry-then-`ValueError` policy). Relying on prompt instructions ("respond with valid JSON matching this schema: ...") plus the existing retry path:

- Works identically across all 4 fallback models, regardless of which ones happen to support constrained decoding — no per-model branching in `get_json_llm()`.
- Matches the stated contract in this ADR's brief: "best-effort JSON in, existing retry/error path handles malformed output" — no new guarantee is being promised that the codebase doesn't already handle the absence of.
- Avoids taking a dependency on `response_format` semantics that would need per-model verification against NIM docs before shipping (deferred, not solved, by this choice — see Open Questions).

**Rejected for now:** per-model `response_format={"type": "json_object"}` binding — real accuracy upside if it works, but requires verifying support per model in `LLM_MODELS` against current NIM docs (not assumed), and doesn't remove the need for the existing retry path anyway (a model can return syntactically valid JSON that still fails schema validation). Revisit only if evals show malformed-JSON retry rate is a meaningful cost post-migration.

### New dependency

`requirements.txt` (confirmed as CalAI's actual dependency file — no `pyproject.toml` present):

```diff
 python-dotenv
 langchain
 langchain-core
-langchain-ollama
+langchain-nvidia-ai-endpoints==1.4.3
 langchain-community
 tavily-python
 pydantic
 langsmith
 fastapi
 uvicorn
```

`langchain-ollama` is removed outright (full replacement, no dual-provider dependency). Pin `==1.4.3` to match the version already validated working in GOT_RAG, rather than an unpinned `>=`.

### Test impact

Existing tests (`test_agent_service.py`, `test_meal_parse_agent.py`, `test_intent_classification_eval.py`) monkeypatch `agent_service.get_json_llm` / `meal_parse_agent.get_json_llm` as a bare zero-arg callable returning a fake LLM object, e.g. `monkeypatch.setattr(agent_service, "get_json_llm", lambda: FakeLLM(...))`. The redesign above **preserves this exactly** — `get_json_llm()` stays zero-arg, returns one object. No test-contract break there.

`get_llm()` gains an optional `tools` parameter (default `None`) — any existing test/call site invoking `get_llm()` with no arguments is unaffected. Only the one call site that currently does `get_llm().bind_tools(tools)` needs updating to `get_llm(tools=tools)`, per the ordering constraint above. `ai-engineer` must grep for all `get_llm(` call sites (not just `agent_service.py:346`) before assuming this is the only one — `api/routes.py`'s `Depends(get_llm)` usage in particular needs to be re-examined since DI happens before the tool list is known (see ordering section above).

---

## Options Considered

### Option A: Keep Ollama, add a second local model as manual fallback
Pull a second, smaller Ollama model locally and manually retry against it if the primary model errors, without leaving the local-only deployment model.

| Dimension | Assessment |
|---|---|
| Effort | Low — no new dependency, no API key management |
| Fixes ADR-005's reachability blocker | No — still a single local process; if Ollama itself is down (not just one model), both "fallback" models are equally unreachable |
| Fixes portability (CI, reviewer machines, deployed backend) | No — still requires every environment to have Ollama installed and models pulled |
| Redundancy | Partial, and fake — the two "different" models share the exact same single point of failure (the local Ollama daemon), so this doesn't actually diversify the failure mode it's meant to address |
| Resume/narrative value | Weak — "added a second local model" doesn't demonstrate handling a real hosted-provider failure mode (rate limits, quota, multi-provider fallback), which is the more realistic production concern |

**Rejected:** solves none of the three costs in Context. It patches over model *choice* redundancy while leaving the actual single point of failure (the Ollama process itself, and the fact that it only exists on one machine) completely unaddressed.

### Option B: Full replacement to NVIDIA NIM, 4-model fallback chain, no rollback flag ✅ (Chosen)
As described in Decision above — reuses GOT_RAG's proven `get_raw_clients` / `with_retry` / `with_fallback_chain` pattern.

| Dimension | Assessment |
|---|---|
| Effort | Medium — one new dependency, one config addition (`NVIDIA_API_KEY`), a provider-file rewrite, one call-site fix for `.bind_tools()` ordering |
| Fixes ADR-005's reachability blocker | Yes — as a side effect, chat LLM calls no longer depend on a local process being up |
| Fixes portability | Yes — any environment with an `NVIDIA_API_KEY` can run the full backend, including CI and a reviewer's machine |
| Redundancy | Real — 4 distinct models from 3 distinct model families/providers-of-record on NIM, with per-model retry absorbing NIM's documented free-tier 503 behavior |
| Resume/narrative value | Strong — demonstrates handling a real hosted multi-provider fallback chain (retry, fallback ordering, tool-binding-before-wrapping constraint), a pattern directly transferable to any other hosted-LLM integration |
| Cost | New: requires an NVIDIA API key and is subject to NIM's rate limits / free-tier quota — a real operational dependency that didn't exist with local Ollama |
| Risk | Model IDs in `LLM_MODELS` are not verified live as of this ADR — must be checked before shipping (Action Item 1) |

---

## Consequences

**Becomes easier:**
- Running the backend anywhere other than the one machine with Ollama + the right model pulled — CI, a reviewer's laptop, a real deployment.
- Resuming ADR-005's blocked phases, since the reachability blocker they're stuck on goes away as a side effect of this migration.
- Demonstrating a real multi-model fallback pattern (retry-per-model absorbing rate-limit errors, ordered fallback chain, tool-binding-before-wrapping) as a resume artifact — a more realistic production concern than a single local model.

**Becomes harder:**
- Requires a real, provisioned `NVIDIA_API_KEY` to run anything that touches the chat LLM surface — local development without one is not possible post-migration (there is deliberately no `USE_ORCHESTRATOR`-style flag back to Ollama).
- Latency and failure modes are now dependent on NVIDIA's infrastructure and quota, not local hardware — a 503 "Worker local total request limit reached" under light concurrent use is a documented behavior of NIM's free/eval tier (this is exactly what the per-model retry is for, but it's a new class of failure that didn't exist locally).
- **`evals/report/latest.json`'s committed baseline (`qwen2.5:3b`, 33 examples: 100% format validity, 83.6% item precision, 92.0% item recall, 59.3% calorie MAPE, 39.6% confidence calibration) is invalidated by this migration.** Switching the underlying model(s) means the baseline no longer describes what's running. A fresh `python evals/run_eval.py` run against the new `LLM_MODELS` chain is a **required post-implementation action**, not optional — but running it and updating the committed baseline is `reviewer`'s job during implementation review, not an action item of this ADR itself.

**Revisit later:**
- If `response_format`/constrained JSON decoding turns out to be well-supported and stable across all 4 `LLM_MODELS` (verified against current NIM docs, not assumed), the prompt-enforced JSON decision above can be revisited in a follow-up ADR — only with evidence the prompt-only approach has a meaningful malformed-JSON retry rate in production traces.
- If `LLM_MODELS`'s specific 4 models turn out to have meaningfully different quality on `parse_meal_text` (visible once the fresh eval baseline lands), the fallback order may need re-ranking by measured accuracy, not just by the order inherited from GOT_RAG's config.

---

## Action Items

1. [ ] Verify all 4 model IDs in `LLM_MODELS` are live on build.nvidia.com as of implementation time — `ai-engineer` confirms via NIM catalog/docs before merging, not assumed from this ADR's text.
2. [ ] `calai_backend/config.py`: `OLLAMA_BASE_URL` and `MODEL_NAME` removed entirely; `NVIDIA_API_KEY` and `LLM_MODELS` (4-model chain, in the order given above) added — verify: `grep -rn "OLLAMA_BASE_URL\|MODEL_NAME" calai_backend/` returns no matches outside this ADR/archdocs and git history.
3. [ ] `requirements.txt`: `langchain-ollama` removed, `langchain-nvidia-ai-endpoints==1.4.3` added — verify: `pip install -r requirements.txt` succeeds in a clean venv, `python -c "import langchain_nvidia_ai_endpoints"` succeeds, `python -c "import langchain_ollama"` fails with `ModuleNotFoundError`.
4. [ ] `calai_backend/providers/llm.py` rewritten per the Decision section's contract: `_raw_clients`, `_with_retry_and_fallback`, `get_llm(tools=None)`, `get_json_llm()` — verify: `get_llm()` and `get_json_llm()` both remain zero-required-arg callables returning a single `BaseChatModel`-compatible object (no tuple/list return).
5. [ ] Full grep pass for every `get_llm(` and `get_json_llm(` call site in `calai_backend/` (not just the two named in this ADR) — each updated to the new contract; `.bind_tools()` is called only on raw (pre-retry/fallback) clients, never on a `RunnableRetry`/`RunnableWithFallbacks` object — verify: `grep -rn "\.bind_tools(" calai_backend/` shows `bind_tools` only inside `providers/llm.py`'s `get_llm`, not at any downstream call site like `agent_service.py`.
6. [ ] `api/routes.py`'s `Depends(get_llm)` usage re-examined and updated per the ordering constraint (DI happens before the tool list is known) — verify: `reviewer` confirms the `/agent` route still produces a tool-bound LLM for the ReAct loop, with no `AttributeError: 'RunnableWithFallbacks' object has no attribute 'bind_tools'` at runtime.
7. [ ] `NVIDIA_API_KEY` documented in `.env.example` (or equivalent) as a required variable — verify: file exists and lists it (do not read/display any actual `.env` file with a real key during this check).
8. [ ] Existing test suite passes unmodified except for necessary mock-target updates — verify: `pytest calai_backend/tests/ -v` passes; `git diff` on test files shows only mechanical `monkeypatch.setattr` target renames if any, no test logic rewritten to accommodate the new provider shape.
9. [ ] One live smoke call against the real NIM endpoint (not mocked) confirms end-to-end connectivity and fallback wiring — verify: a manual `/api/agent` request completes successfully with `NVIDIA_API_KEY` set, and `reviewer` confirms in review notes which of the 4 models actually answered (primary vs. a fallback firing).
10. [ ] Post-implementation (not an item to execute as part of this ADR, called out per the Consequences section): `python evals/run_eval.py` re-run against the new provider, `evals/report/latest.json` updated with the new baseline — flagged here so `reviewer` treats "baseline still says qwen2.5:3b" as an open finding, not this ADR's responsibility to close.

---

## Open Questions

- Whether `response_format`/constrained JSON decoding is reliably supported across all 4 `LLM_MODELS` is genuinely unverified — this ADR deliberately defers that investigation (see JSON-mode decision) rather than guessing; if `ai-engineer` finds strong native JSON support during implementation, that's grounds for a follow-up ADR, not a silent deviation from the prompt-enforced approach decided here.
- NIM's free/eval tier rate limits (request/min, concurrent request caps) are not quantified in this ADR beyond "GOT_RAG observed 503s under light concurrent use" — if CalAI's request volume differs meaningfully from GOT_RAG's, the `stop_after_attempt=2` retry policy may need tuning; not blocking for initial migration, worth measuring once the smoke test (Action Item 9) is running.
