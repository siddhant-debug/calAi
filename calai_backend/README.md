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

Meal parsing and the agent path are backed by **NVIDIA NIM**
(`langchain-nvidia-ai-endpoints`, `ChatNVIDIA`) as of ADR-006
(`../archdocs/ADR-006-nvidia-nim-migration.md`) — full replacement of the
previous local-Ollama provider, no rollback flag. Calls go through a
retry+fallback chain (`config.py`'s `LLM_MODELS`), so a single
model being slow/rate-limited/down on NIM doesn't take down the whole
chat LLM surface.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r ../requirements.txt
```

Set `NVIDIA_API_KEY` in `.env` (see `../.env.example`) — get one at
https://build.nvidia.com. There is no local-model fallback; every
LLM-dependent route requires this to be set.

## Configuration

Environment variables (optionally via a `.env` file, see `config.py`):

| Variable | Default | Description |
|---|---|---|
| `NVIDIA_API_KEY` | `""` | Required — NVIDIA NIM API key for the chat LLM provider |
| `MAX_STEPS` | `8` | Max tool-call iterations for the legacy ReAct loop only |
| `USE_ORCHESTRATOR` | `true` | `true` → deterministic Orchestrator (default); `false` → legacy ReAct loop |

`LLM_MODELS` (the NIM fallback chain, in order) is set in
`config.py`, not via an env var — see ADR-006 for the original rationale
(the chain was reduced from 4 to 2 models after 3 were found retired by
NVIDIA post-migration; `config.py`'s comment has the current list and why).

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
providers/llm.py               ChatNVIDIA client factory (NVIDIA NIM, retry+fallback chain, ADR-006)
services/agent_service.py      run_agent() — Orchestrator (default) + legacy ReAct loop
services/calc_pipeline.py      run_calc_pipeline() — deterministic, no LLM
services/meal_parse_agent.py   parse_meal() — isolated, evaluated meal-parsing call
prompts/calai_prompt.py        Legacy ReAct loop's system prompt
tools/                         bmr, tdee, calorie_goal, meal_parser (thin wrapper) + tool registry
```
