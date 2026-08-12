# CalAI Backend

FastAPI service for calorie tracking. Provides direct BMR/TDEE/calorie-goal
calculations, LLM-based meal parsing, and an `/api/agent` endpoint that
chains them based on natural-language input.

As of ADR-003 (`../archdocs/ADR-003-multiagent-split.md`), `/api/agent`
defaults to a deterministic **Orchestrator** (`services/agent_service.py`'s
`_run_agent_orchestrator`) — plain-Python routing that calls the
deterministic `CalcPipeline` (`services/calc_pipeline.py`) and the isolated,
evaluated `MealParseAgent` (`services/meal_parse_agent.py`) directly, instead
of letting an LLM decide tool order in a ReAct loop. The old ReAct loop
(`_run_agent_react_loop`) is still in the codebase and reachable via
`USE_ORCHESTRATOR=false`, for rollback/comparison — see
`../artefacts/NOTES-orchestrator-vs-react.md` for an honest tradeoff writeup
and `../artefacts/adr003-latency-comparison.json` for the measured 2.25x
speedup.

Meal parsing and the agent path are backed by a local
[Ollama](https://ollama.com) model via `langchain-ollama`.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn langchain langchain-core langchain-ollama pydantic python-dotenv httpx
```

Pull and run the model:

```bash
ollama pull qwen2.5:3b
ollama serve
```

`config.py`'s `MODEL_NAME` env-var default is still `qwen2.5:7b`, but nothing
pulls that automatically — set `MODEL_NAME=qwen2.5:3b` in `.env`, or confirm
what's actually live with `curl localhost:11434/api/tags` before assuming
the default is what's running.

## Configuration

Environment variables (optionally via a `.env` file, see `config.py`):

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `MODEL_NAME` | `qwen2.5:7b` (set to `qwen2.5:3b` in practice) | Model used for meal parsing and the agent path |
| `MAX_STEPS` | `8` | Max tool-call iterations for the legacy ReAct loop only |
| `USE_ORCHESTRATOR` | `true` | `true` → deterministic Orchestrator (default); `false` → legacy ReAct loop |

## Run

```bash
uvicorn calai_backend.main:app --reload
```

(Run from the parent directory that contains `calai_backend/`, so the
`calai_backend.*` imports resolve.)

## API

### `GET /api/health`

Health check.

```bash
curl http://localhost:8000/api/health
```

### `POST /api/calculate`

Direct BMR → TDEE → calorie-goal calculation, no LLM involved.

```bash
curl -X POST http://localhost:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{
    "weight_kg": 70,
    "height_cm": 175,
    "age": 30,
    "gender": "male",
    "activity_level": "moderately_active",
    "goal": "lose",
    "goal_rate_kg_per_week": 0.5
  }'
```

### `POST /api/parse-meal`

Parses a natural-language meal description into structured nutrition data
using the LLM in JSON mode.

```bash
curl -X POST http://localhost:8000/api/parse-meal \
  -H "Content-Type: application/json" \
  -d '{"meal_text": "two eggs and a slice of toast", "meal_type": "breakfast"}'
```

### `POST /api/agent`

Runs the Orchestrator by default — deterministic routing that calls
`CalcPipeline` and/or `MealParseAgent` based on which fields the input
message implies. Set `USE_ORCHESTRATOR=false` to route through the legacy
ReAct loop instead.

```bash
curl -X POST http://localhost:8000/api/agent \
  -H "Content-Type: application/json" \
  -d '{"message": "I weigh 70kg, 175cm, 30yo male, moderately active, want to lose weight"}'
```

## Project layout

```
main.py                        FastAPI app entrypoint
config.py                      Env-var configuration (incl. USE_ORCHESTRATOR)
schemas.py                     Pydantic request/response models
api/routes.py                  Route handlers
providers/llm.py               ChatOllama client factory
services/agent_service.py      run_agent() — Orchestrator (default) + legacy ReAct loop
services/calc_pipeline.py      run_calc_pipeline() — deterministic, no LLM
services/meal_parse_agent.py   parse_meal() — isolated, evaluated meal-parsing call
prompts/calai_prompt.py        Legacy ReAct loop's system prompt
tools/                         bmr, tdee, calorie_goal, meal_parser (thin wrapper) + tool registry
```
