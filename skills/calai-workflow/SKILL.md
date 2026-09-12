---
name: calai-workflow
description: >
  Workflow guide for AI engineering on the CalAI project. Use this skill
  whenever the user explicitly says "use this skill" while working on CalAI.
  Covers: adding LangChain tools to calai_agent.py, building FastAPI endpoints
  in calai_backend/, debugging NVIDIA NIM/LangChain connection issues, and running tests.
---

# CalAI Workflow Skill

## Project at a Glance

**What it is:** A calorie-tracking AI with two tracks:
- `calai_agent.py` — learning track: manually built LangChain ReAct agent (THOUGHT → ACTION → OBSERVE loop)
- `calai_backend/` — production track: FastAPI server, deterministic `Orchestrator` by default (ADR-003), legacy ReAct loop behind `USE_ORCHESTRATOR=false`

**Chat LLM provider:** NVIDIA NIM (`ChatNVIDIA`) as of ADR-006 — full replacement of the old local-Ollama setup, no rollback flag. `config.py`'s `LLM_MODELS` is a retry+fallback chain; `NVIDIA_API_KEY` (in `calai_backend/.env`) is required, no local-model fallback. **Do not assume a model ID in `LLM_MODELS` is live** — NVIDIA retires NIM-hosted models over time and the catalog's own `deprecated` flag has been observed to disagree with what a real call returns. Verify with `python evals/run_eval.py --model <id>` (or a direct `parse_meal_text` smoke call) before relying on or adding one.

**Key files:**
- `calai_agent.py` — single-file agent + all tools (learning track, standalone)
- `calai_backend/` — the actual production backend (see "Track 2" below for its real, current layout)
- `evals/` — accuracy harness for `parse_meal_text`/`MealParseAgent` (ADR-004); `evals/README.md` is the how-to
- `archdocs/ADR-*.md` — the design record; read the relevant ones before nontrivial changes

---

## Track 1: Adding a Tool to `calai_agent.py`

Every tool follows this pattern:

```python
@tool
@traceable(name="tool_name")
def tool_name(param: type) -> return_type:
    """One-line description the LLM uses to decide when to call this tool.
    Enumerate valid values for any constrained params here."""
    # validate inputs, raise ValueError for bad values
    # compute result
    return round(result, 1)
```

**Checklist when adding a tool:**
1. Write the function with `@tool` + `@traceable`
2. Add it to `tools = [...]` in `run_agent`
3. Add it to `tools_dict` (handled automatically by the dict comprehension)
4. Update `SYSTEM_PROMPT` to mention the tool and when to call it
5. Test with a `run_agent(...)` call that exercises it end-to-end

**The agent loop contract:**
- `llm_with_tools.invoke(messages)` → returns `ai_message`
- `ai_message.tool_calls` → list of `{name, args, id}` dicts
- Empty `tool_calls` = LLM is done → `ai_message.content` is the final answer
- Feed results back via `ToolMessage(content=str(result), tool_call_id=id)`

This learning-track file (`calai_agent.py`) is intentionally kept separate from `calai_backend/` and still uses its own direct LLM client setup — check its current imports before assuming it shares `providers/llm.py` with the backend.

---

## Track 2: `calai_backend/` — the real production layout

This is built and running, not a plan — the structure below is what actually exists today (see `calai_backend/README.md` for the fuller version):

```
calai_backend/
├── main.py                   # FastAPI app + lifespan
├── config.py                 # NVIDIA_API_KEY, LLM_MODELS (fallback chain), MAX_STEPS, USE_ORCHESTRATOR
├── schemas.py                # Pydantic request/response models
├── .env                      # NVIDIA_API_KEY (not committed) — see ../.env.example
├── api/
│   └── routes.py             # /api/health, /api/calculate, /api/parse-meal, /api/agent
├── providers/
│   └── llm.py                # ChatNVIDIA client factory — get_llm()/get_json_llm(), retry+fallback (ADR-006)
├── services/
│   ├── agent_service.py      # run_agent() — Orchestrator (default) + legacy ReAct loop
│   ├── calc_pipeline.py      # run_calc_pipeline() — deterministic BMR→TDEE→goal, no LLM
│   └── meal_parse_agent.py   # parse_meal() — isolated, eval-gated meal-parsing call
├── tools/                    # Plain-Python functions (NO @tool decorator — wrappers live in api/routes.py)
│   ├── bmr.py
│   ├── tdee.py
│   ├── calorie_goal.py
│   └── meal_parser.py        # thin wrapper around services/meal_parse_agent.py
└── tests/                    # pytest — plain functions, no LLM calls, exact input→output
```

**Adding a new endpoint:**
1. If it needs an LLM call, get the client via `providers/llm.py`'s `get_llm()`/`get_json_llm()` — never construct a `ChatNVIDIA` instance directly elsewhere, that's how the retry+fallback chain gets bypassed.
2. Add/extend Pydantic models in `schemas.py`.
3. Wire the route in `api/routes.py`. `@tool` wrappers (if the route needs to be agent-callable) live here, not in `tools/`.
4. If the new logic is nondeterministic (calls an LLM), it needs eval coverage, not just a pytest unit test — see `evals/README.md` and `archdocs/ADR-004-eval-harness.md`. If it's pure computation, a `calai_backend/tests/` pytest case with exact input→output is enough.

**Running the backend:**
```bash
# from the repo root, so calai_backend.* imports resolve
uvicorn calai_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Debugging NVIDIA NIM / LangChain Issues

| Symptom | Cause | Fix |
|---|---|---|
| `401 Unauthorized` | Wrong/missing `NVIDIA_API_KEY`, or `.env` loaded from the wrong path | Check `dotenv_values('calai_backend/.env').keys()` for the exact var name (names only, never print values) — a stale `.env` elsewhere in the repo can shadow the real one if `load_dotenv()` isn't anchored to `calai_backend/`'s own directory |
| `410 Gone` on a specific model | NVIDIA retired that model | Don't add/keep it in `LLM_MODELS` — verify replacements with `python evals/run_eval.py --model <id>` before relying on the catalog's `deprecated` flag |
| `503` / rate-limited | NIM's free/eval tier request limit | This is what `LLM_MODELS`'s fallback chain exists for — confirm the chain actually has more than one *live* model, not just more than one entry |
| Agent loops to MAX_STEPS | LLM not following tool order (legacy ReAct path only) | Strengthen the system prompt, add a few-shot example. The default Orchestrator path (`USE_ORCHESTRATOR=true`) has no iteration loop to get stuck in |
| Tool args wrong type | Model hallucinating param names | Add explicit param names + types in the tool's docstring |
| `.bind_tools()` has no effect | Called on an already-wrapped (retry/fallback) client | Must be called on the raw client *before* `with_retry`/`with_fallbacks` wrapping — `RunnableRetry`/`RunnableWithFallbacks` aren't `BaseChatModel` and silently don't forward it. See `providers/llm.py`'s `_raw_clients()`/`get_llm()` split. |

---

## Running Tests

```bash
cd /Users/siddhanttomar/Claude/Projects/calAi
source .venv/bin/activate

# Learning track — run the agent directly
python calai_agent.py

# Backend unit tests (deterministic tools, schemas, routes — no LLM calls)
pytest calai_backend/tests/ -v

# Eval harness (parse_meal_text accuracy — real LLM calls, several minutes)
cd evals && python run_eval.py
```

---

## Key Conventions

- `temperature=0` where determinism matters (tool selection, structured extraction) — check the specific client construction in `providers/llm.py` rather than assuming a project-wide default.
- All math tools are pure Python — LLM only decides *which* tool to call (legacy ReAct path) or the Orchestrator routes to them directly (default path).
- Tool docstrings are the LLM's only guide — make them precise and enumerate valid values.
- Never read `.env` — ask the user for env var values if needed; use `dotenv_values(path).keys()` (names only) if you need to confirm a variable name exists, never its value.
- Read `archdocs/ADR-*.md` for current status and design rationale — `AGENT-HANDOFF.md` (if present) is older session-state notes, not the source of truth once an ADR covers the same ground.
