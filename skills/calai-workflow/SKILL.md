---
name: calai-workflow
description: >
  Workflow guide for AI engineering on the CalAI project. Use this skill
  whenever the user explicitly says "use this skill" while working on CalAI.
  Covers: adding LangChain tools to calai_agent.py, building FastAPI endpoints
  in calai_backend/, debugging Ollama/LangChain connection issues, and running tests.
---

# CalAI Workflow Skill

## Project at a Glance

**What it is:** A calorie-tracking AI with two tracks:
- `calai_agent.py` — learning track: manually built LangChain ReAct agent (THOUGHT → ACTION → OBSERVE loop)
- `calai_backend/` — production track: FastAPI server wrapping the same agent logic

**Model:** `qwen2.5:3b` via Ollama at `localhost:11434` (tunnelled from `192.168.1.58` via SSH)
**Key files:**
- `calai_agent.py` — single-file agent + all tools
- `learning.md` — step-by-step roadmap for the learning track
- `AGENT-HANDOFF.md` — session state, pending work, design decisions
- `requirements.txt` — Python deps

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

### Pending tools (from `learning.md`)

**Step 4 — `parse_meal_text`**
- Nested Ollama call with `format="json"` on a `ChatOllama` instance
- Returns: `{items: [{name, quantity, unit, calories_kcal, protein_g, carbs_g, fat_g}], total_kcal, meal_type}`
- Use a dedicated `ChatOllama(model=MODEL, base_url=base_url, format="json")` instance — don't reuse the bound one

**Step 5 — `save_meal`**
- `sqlite3` — open/create `calai.db`, create meals table if not exists
- Schema: `(id INTEGER PRIMARY KEY, date TEXT, meal_type TEXT, total_kcal REAL, data_json TEXT)`
- Insert with `datetime.date.today().isoformat()` and `json.dumps(parsed_meal)`

**Step 6 — `get_daily_summary`**
- Query `calai.db` WHERE date = target date
- Return `{"date": date, "meals_logged": n, "total_kcal": total}`

---

## Track 2: FastAPI Endpoint in `calai_backend/`

The planned backend structure (not yet created):

```
calai_backend/
├── main.py              # FastAPI app + lifespan
├── config.py            # OLLAMA_URL, MODEL_NAME, MAX_STEPS
├── agent/
│   ├── react_loop.py    # ReActAgent class
│   ├── llm_client.py    # OllamaClient (httpx, timeout=60s)
│   └── schemas.py       # Pydantic I/O models
├── tools/               # Pure-Python tool functions (no @tool decorator)
│   ├── bmr.py
│   ├── tdee.py
│   └── calorie_goal.py
├── api/
│   └── routes.py        # /agent, /calculate, /summary, /profile
├── db/
│   ├── database.py      # SQLite engine + get_session()
│   └── models.py        # ORM models
└── tests/
    ├── test_tools.py
    └── test_react_loop.py
```

**Next endpoint to build: `POST /api/calculate`**

```json
// Request
{"weight_kg": 57, "height_cm": 175, "age": 25, "gender": "male",
 "activity_level": "lightly_active", "goal": "gain", "goal_rate_kg_per_week": 0.5}

// Response
{"bmr_kcal": 1596.3, "tdee_kcal": 2194.9, "calorie_goal_kcal": 2744.9}
```

Implementation steps:
1. Extract `calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal` from `calai_agent.py` into `tools/` as plain functions (no `@tool`)
2. Add `CalcRequest` / `CalcResponse` Pydantic models in `agent/schemas.py`
3. Wire `POST /api/calculate` in `api/routes.py` — call functions directly in order
4. FastAPI + Pydantic handles 422 validation automatically

**Running the backend:**
```bash
cd calai_backend
source ../.venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Debugging Ollama / LangChain Issues

| Symptom | Cause | Fix |
|---|---|---|
| `httpx.ConnectError` | Ollama not running | `ollama serve` (or check SSH tunnel) |
| `httpx.ReadError` (errno 54) | Model not downloaded | `ollama pull qwen2.5:3b` |
| `httpx.HTTPStatusError` | Bad request/model name | Print `e.response.text` for details |
| Agent loops to MAX_ITERATIONS | LLM not following tool order | Strengthen SYSTEM_PROMPT, add few-shot example |
| Tool args wrong type | Model hallucinating param names | Add explicit param names + types in docstring |
| `/api/agent` timeout | SSH tunnel latency or cold-start | `time curl localhost:11434/v1/chat/completions ...` to isolate |

**SSH tunnel (Ollama on remote machine):**
```bash
ssh -L 11434:localhost:11434 sidtom@192.168.1.58 -N -f
```

**Check what models are available:**
```bash
ollama list
```

---

## Running Tests

```bash
cd /Users/siddhanttomar/Claude/Projects/calAi
source .venv/bin/activate

# Learning track — run the agent directly
python calai_agent.py

# Backend tests (once calai_backend/ exists)
cd calai_backend
pytest tests/ -v
```

---

## Key Conventions

- `temperature=0` on every `ChatOllama` — deterministic tool selection
- All math tools are pure Python — LLM only decides *which* tool to call
- `@traceable` on every tool + `run_agent` — LangSmith tracing (currently disabled in `.env`)
- Tool docstrings are the LLM's only guide — make them precise and enumerate valid values
- Never read `.env` — ask user for env var values if needed
- Check `AGENT-HANDOFF.md` at session start for current status and pending work
