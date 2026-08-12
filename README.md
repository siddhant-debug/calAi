# CalAI — AI-Enabled Calorie Tracker

A privacy-first calorie tracker where you log meals in plain English. A local Orchestrator (`calai_backend/services/agent_service.py`, powered by `qwen2.5:3b` via Ollama) parses your input, computes your calorie goal, and tracks your day — 100% offline.

**Stack:** Python FastAPI · LangChain · Ollama `qwen2.5:3b` · SQLite (coming in Step 5)

**Architecture note:** as of ADR-003 (`archdocs/ADR-003-multiagent-split.md`), `/api/agent` runs through a deterministic `Orchestrator` (plain Python routing + a `CalcPipeline` + an isolated `MealParseAgent`) instead of a single ReAct tool-calling loop — 2.25x faster in measured testing, with the old ReAct loop kept in the codebase behind a `USE_ORCHESTRATOR=false` flag for rollback. See `artefacts/NOTES-orchestrator-vs-react.md` for an honest advantages/disadvantages writeup and `artefacts/adr003-latency-comparison.json` for the raw numbers.

---

## Quick Start

### Prerequisites

- [Ollama](https://ollama.com) installed and running with `qwen2.5:3b` pulled — this is the only model actually verified live for this project (confirm any time with `curl localhost:11434/api/tags`); `config.py`'s `MODEL_NAME` default is `qwen2.5:7b` but nothing pulls that automatically, so set `MODEL_NAME=qwen2.5:3b` in `.env` if you haven't
- Python 3.11+
- Virtual environment set up

```bash
ollama pull qwen2.5:3b
ollama serve
```

### Install dependencies

```bash
cd /Users/siddhanttomar/Claude/Projects/calAi
source .venv/bin/activate
pip install -r requirements.txt
```

### Option A — CLI (interactive)

```bash
python calai_agent.py
```

Type anything in plain English:

```
You: I am 25M, 75kg, 175cm, lightly active, want to lose 0.5kg/week.
You: I had 2 scrambled eggs and a banana for breakfast.
You: quit
```

### Option B — FastAPI backend

```bash
uvicorn calai_backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Docs at: `http://localhost:8000/docs`

---

## Project Structure

```
calAi/
├── calai_agent.py               # Standalone CLI — ReAct loop + all tools
├── requirements.txt
├── .env                         # OLLAMA_BASE_URL, MODEL_NAME (optional overrides)
│
└── calai_backend/               # FastAPI backend
    ├── main.py                  # App entry point, logging config
    ├── config.py                # OLLAMA_BASE_URL, MODEL_NAME, MAX_STEPS
    ├── schemas.py               # Pydantic request/response models
    ├── api/
    │   └── routes.py            # All route handlers
    ├── services/
    │   ├── agent_service.py     # run_agent() — Orchestrator (default) + legacy ReAct loop, behind USE_ORCHESTRATOR flag
    │   ├── calc_pipeline.py     # run_calc_pipeline() — deterministic BMR→TDEE→goal, no LLM
    │   └── meal_parse_agent.py  # parse_meal() — isolated, evaluated meal-parsing LLM call
    └── tools/
        ├── bmr.py               # calculate_bmr()
        ├── tdee.py              # calculate_tdee()
        ├── calorie_goal.py      # calculate_calorie_goal()
        └── meal_parser.py       # thin wrapper around services/meal_parse_agent.py
```

See `archdocs/ADR-003-multiagent-split.md` for why the split happened and `evals/README.md` + `archdocs/ADR-004-eval-harness.md` for how `parse_meal_text`/`MealParseAgent` accuracy is measured and gated.

---

## API Reference

### `GET /api/health`

```json
{ "status": "ok" }
```

---

### `POST /api/calculate`

Direct calculation — no LLM involved. BMR → TDEE → calorie goal in one shot.

**Request:**
```json
{
  "weight_kg": 75,
  "height_cm": 175,
  "age": 25,
  "gender": "male",
  "activity_level": "lightly_active",
  "goal": "lose",
  "goal_rate_kg_per_week": 0.5
}
```

**Response:**
```json
{
  "bmr_kcal": 1822.5,
  "tdee_kcal": 2505.9,
  "calorie_goal_kcal": 2055.9
}
```

---

### `POST /api/parse-meal`

Parses a natural-language meal description into structured nutrition data using the LLM.

**Request:**
```json
{
  "meal_text": "2 scrambled eggs, a slice of whole wheat toast, and a glass of orange juice",
  "meal_type": "breakfast"
}
```

**Response:**
```json
{
  "items": [
    { "name": "scrambled eggs", "quantity": 2, "unit": "piece", "calories_kcal": 108, "protein_g": 13.6, "carbs_g": 1.5, "fat_g": 9.7 },
    { "name": "whole wheat toast", "quantity": 1, "unit": "slice", "calories_kcal": 80, "protein_g": 2.6, "carbs_g": 14.3, "fat_g": 1.5 },
    { "name": "orange juice", "quantity": 1, "unit": "glass", "calories_kcal": 97, "protein_g": 0.8, "carbs_g": 23.6, "fat_g": 0.0 }
  ],
  "total_kcal": 285,
  "meal_type": "breakfast",
  "model_latency_ms": 4210.5
}
```

---

### `POST /api/agent`

Runs the Orchestrator by default (deterministic routing + `CalcPipeline` + `MealParseAgent`) — understands free-text input and calls the tools its shape implies. Set `USE_ORCHESTRATOR=false` to route through the legacy ReAct tool-calling loop instead (kept for rollback/comparison, see `archdocs/ADR-003-multiagent-split.md`).

**Request:**
```json
{ "message": "I am 25M, 75kg, 175cm, lightly active, want to gain 0.5kg/week." }
```

**Response:**
```json
{
  "response": "Your daily calorie goal to gain 0.5 kg/week is approximately 2906 kcal...",
  "iterations_used": 4
}
```

**Error responses:**

| Code | Meaning |
|------|---------|
| `422` | Invalid field value (bad gender, activity level, goal, etc.) |
| `503` | Ollama not reachable — run `ollama serve` |
| `502` | Ollama returned unexpected HTTP error |
| `500` | Agent hit MAX_STEPS without a final answer |

---

## Tools Reference

| Tool | Calls LLM? | Implemented |
|------|-----------|-------------|
| `calculate_bmr` | No | Yes |
| `calculate_tdee` | No | Yes |
| `calculate_calorie_goal` | No | Yes |
| `parse_meal_text` | **Yes** (nested Ollama call) | Yes |
| `save_meal` | No | Coming — Step 5 |
| `get_daily_summary` | No | Coming — Step 6 |

**Activity levels:** `sedentary` · `lightly_active` · `moderately_active` · `very_active` · `extra_active`

**Goals:** `lose` · `maintain` · `gain`

---

## Configuration

`calai_backend/config.py` reads from environment (`.env` or shell):

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `MODEL_NAME` | `qwen2.5:7b` (config default — set to `qwen2.5:3b` in `.env`, the only model actually pulled) | Model for the agent path and meal parsing |
| `MAX_STEPS` | `8` | Iteration cap for the legacy ReAct loop only (`USE_ORCHESTRATOR=false`) |
| `USE_ORCHESTRATOR` | `true` | `true` → deterministic Orchestrator (default, faster); `false` → legacy ReAct loop |

---

## Troubleshooting

**`Connection refused` on port 11434** — Ollama isn't running. Run `ollama serve`.

**Model not found** — Run `ollama pull qwen2.5:3b` (or whatever `MODEL_NAME` you've set — confirm what's actually pulled with `curl localhost:11434/api/tags`).

**Agent stuck / max iterations** — Only applies on the legacy ReAct path (`USE_ORCHESTRATOR=false`); the default Orchestrator path has no iteration loop to get stuck in. On the legacy path, the 3b model occasionally loses track on very long inputs — shorten the message or split into two queries (stats first, meal second).

**Meal calories seem off** — `parse_meal_text` estimates from the LLM's training data. For precise values, a USDA FoodData Central API lookup tool can be added as Step 7.
