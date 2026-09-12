# CalAI — AI-Enabled Calorie Tracker

A privacy-first calorie tracker where you log meals in plain English. A deterministic Orchestrator (`calai_backend/services/agent_service.py`) routes your input to a pure-Python `CalcPipeline` (BMR → TDEE → calorie goal — no LLM) and an isolated, **eval-gated** `MealParseAgent` that turns "2 rotis with dal" into structured, calorie-scored items.

**Stack:** Python FastAPI · LangChain · NVIDIA NIM (`ChatNVIDIA`) · Flutter (iOS/Android/web) · a from-scratch eval harness, not vibes

This README is written to be readable top-to-bottom by someone deciding whether the engineering here is real — not just a setup guide. If you're here to run it, jump to [Quick Start](#quick-start). If you're here to evaluate the engineering, read on.

---

## The three things this project is actually trying to prove

1. **An LLM feature's correctness is a measured number, not a screen recording.** → [How accuracy is evaluated](#how-accuracy-is-evaluated)
2. **An architectural decision (single LLM loop vs. deterministic orchestration) can be settled with data, not preference.** → [Why the Orchestrator is faster](#why-the-orchestrator-is-faster)
3. **The codebase itself can be built and kept correct by a coordinated set of specialized agents with an enforced review gate, not one undifferentiated "AI writes code" loop.** → [How this codebase gets built](#how-this-codebase-gets-built)

---

## How accuracy is evaluated

`parse_meal_text` — the only nondeterministic component in the backend — turns free text into structured, calorie-scored items. Every other tool (`calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal`) is pure arithmetic; a unit test fully specifies it. An LLM's output can't be graded that way, so it gets a real harness instead of a vibe check: **`evals/run_eval.py`**, spec'd in [`archdocs/ADR-004-eval-harness.md`](archdocs/ADR-004-eval-harness.md).

**The design decision that makes this work:** grading against calorie *ranges*, not exact numbers. A "large egg" and a "medium egg" genuinely differ in calories — grading against one exact value would fail correct-but-differently-estimated answers. Ranges are sourced from USDA data.

**Five scoring dimensions, on a 70-example golden dataset across 5 cuisine/meal-type categories:**

| Metric | What it measures | Current baseline (NVIDIA NIM chain, 70 examples) |
|---|---|---|
| `format_valid_pct` | Did the model produce parseable JSON matching the schema — a hard gate before anything else scores | 100.0% |
| `item_precision_pct` | Of the items extracted, how many were real (not hallucinated) | 91.2% |
| `item_recall_pct` | Of the real items, how many were found (not missed) | 99.0% |
| `calorie_mape_pct` | Mean absolute percentage error of calorie estimates vs. the expected range | 37.1% |
| `confidence_calibration_score_pct` | When the model says "low confidence," is it actually wrong more often than on "high confidence" items? | 57.1% |

This is a real, checked-in accuracy timeline, not a one-off screenshot — `git log -p evals/report/latest.json` shows how these numbers moved as the model and provider changed. Two design choices worth calling out specifically:

- **Regressions are gated, not spotted by accident.** `python evals/run_eval.py --gate --baseline evals/report/latest.json` fails (exit 1) if any metric regresses beyond a tolerance — this is what `reviewer` runs before any prompt/model change is considered done, not a manual JSON diff.
- **Per-model comparison is decoupled from fallback-chain availability.** `python evals/run_eval.py --model <name>` scores one model in isolation. This distinction mattered concretely: when migrating to NVIDIA NIM, 3 of the original 4 fallback-chain models (copied from a reference project) turned out to be retired by NVIDIA (`410 Gone`) — found by calling each one for real, since the NIM catalog's own `deprecated` flag disagreed with what the live API actually returned. The chain was rebuilt to 2 verified-live models on the strength of this per-model data, not vendor documentation.
- **Every real-world parse failure becomes a permanent regression case** in `evals/dataset/*.jsonl` — same discipline as adding a unit test for every bug fix.

Full methodology, report-field glossary, and how to add a new golden example: [`evals/README.md`](evals/README.md).

---

## Why the Orchestrator is faster

`/api/agent` used to run a single ReAct loop — an LLM deciding, one tool call at a time, which of `calculate_bmr`/`calculate_tdee`/`calculate_calorie_goal`/`parse_meal_text` to call and in what order. [`archdocs/ADR-003-multiagent-split.md`](archdocs/ADR-003-multiagent-split.md) replaced that with a deterministic `Orchestrator`: plain-Python routing based on which fields a request implies, calling a pure-Python `CalcPipeline` and an isolated `MealParseAgent` directly — no LLM decides *whether* to call `calculate_bmr`, because that was never actually an ambiguous decision.

**Measured result** (3 representative messages, real local-model calls — see [`artefacts/adr003-latency-comparison.json`](artefacts/adr003-latency-comparison.json)):

| Message shape | Old ReAct loop | Orchestrator | Speedup |
|---|---|---|---|
| Profile only | 76.6s | 31.9s | 2.41x |
| Meal only | 150.3s | 73.2s | 2.05x |
| Profile + meal | 176.0s | 74.0s | 2.38x |
| **Total** | **402.9s** | **179.0s** | **2.25x** |

**Why:** the ReAct loop's cost scaled with how many steps the model chose to take (up to `MAX_STEPS=8`) before converging — unpredictable, and expensive on a small local model with no GPU. The Orchestrator's cost is two bounded LLM calls plus fixed-cost Python, because the routing decision itself was never something that needed a language model's judgment.

**This wasn't only a speed win.** On the "profile only" message, the old ReAct loop's LLM-computed TDEE diverged sharply from the correct value (**3726 kcal reported vs. 2678 kcal actual** — the deterministic `CalcPipeline` result) on identical input. A small local model was quietly getting arithmetic wrong when the design let it "help" with a calculation it was only supposed to sequence, not perform. That's a correctness bug the latency comparison surfaced as a side effect, not the headline it was measuring for.

**The honest tradeoffs** — this project keeps the old ReAct loop in the codebase specifically so this comparison could be made fairly (`USE_ORCHESTRATOR=false` still works), and a full retrospective exists that argues against its own conclusion where warranted: reduced generality, `extract_request_fields`'s own accuracy is still unmeasured, and the comparison is one run, not a distribution. Read the unfiltered version: [`artefacts/NOTES-orchestrator-vs-react.md`](artefacts/NOTES-orchestrator-vs-react.md).

---

## How this codebase gets built

This isn't "an AI wrote this repo" — changes go through a coordinated set of specialized agents with defined ownership boundaries and an enforced review gate, specified in [`CLAUDE.md`](CLAUDE.md).

| Agent | Owns | Never touches |
|---|---|---|
| `architecture-designer` | New ADRs — context, rejected options with honest tradeoffs, concrete contracts, a checkable action-item list | Implementation code |
| `ai-engineer` | `calai_backend/` — tools, services, providers, agent/LLM logic | Flutter code, visual design |
| `ui-engineer` | Design tokens, layout, UX spec | `.dart` implementation |
| `flutter-engineer` | `calai_frontend/lib/**/*.dart` | New visual design, backend contracts |
| `tester` | pytest suites, eval golden-dataset cases | Deciding pass/fail — that's `reviewer`'s job |
| `reviewer` | Read-only review + running tests/evals as the gate | Editing anything |
| `sdlc-orchestrator` | Autonomous end-to-end pipeline execution for hands-off runs | Doing the engineering/testing/review work itself |

**The gate that matters:** every unit of work from `ai-engineer` or `flutter-engineer` goes through `tester` (adds coverage) then `reviewer` (runs it, reports bugs vs. optional simplifications) before it's called done — no exception for "small" changes that touch logic. Bugs go back to the owning engineer as a fix brief; if the bug reveals missing coverage, `tester` adds a regression case for it *first*, then re-review. Capped at 2 fix loops — past that, it escalates to a human instead of guessing.

**A concrete example of the gate catching something real:** the NVIDIA NIM migration ([ADR-006](archdocs/ADR-006-nvidia-nim-migration.md)) initially shipped with two stacked `.env` bugs — a stale config file being loaded from the wrong path, and the wrong variable name — that both `tester` and `reviewer` missed on the first pass, because the failure only became live at runtime (a `401 Unauthorized`), not in a diff. The fix wasn't just patching those two bugs: it became a permanent rule in `CLAUDE.md` and in `reviewer`'s and `ai-engineer`'s own instructions — any change that makes a previously-optional `.env` value required now requires an explicit, independently-re-run check of the exact variable name, via `dotenv_values(path).keys()` (names only, secrets never read or printed). The process that builds this repo revises itself when it finds a gap, the same way the eval baseline revises itself when a model changes.

---

## Quick Start

### Prerequisites

- An [NVIDIA NIM](https://build.nvidia.com) API key — set `NVIDIA_API_KEY` in `calai_backend/.env` (see `.env.example`). There is no local-model fallback; every LLM-dependent route requires this.
- Python 3.11+, virtual environment set up
- [Flutter](https://flutter.dev) (stable channel) if you're also running the app frontend — `flutter doctor` should show a clean iOS/Android/web toolchain

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

### Option C — Flutter app

```bash
cd calai_frontend
flutter run
```

See `calai_frontend/README.md` for device setup. Note: the frontend is currently a visual mockup on hardcoded data — it doesn't yet call the backend above. See `calai_frontend/README.md` for exactly what's wired up vs. stubbed.

---

## Project Structure

```
calAi/
├── calai_agent.py                # Standalone CLI — ReAct loop + all tools
├── requirements.txt
├── archdocs/                     # ADRs — the design record (ADR-001 through ADR-006)
├── artefacts/                    # Measured evidence backing decisions (latency comparisons, etc.)
│
├── calai_backend/                # FastAPI backend
│   ├── main.py                   # App entry point, logging config
│   ├── config.py                 # NVIDIA_API_KEY, LLM_MODELS (fallback chain), MAX_STEPS
│   ├── schemas.py                # Pydantic request/response models
│   ├── .env                      # NVIDIA_API_KEY (see .env.example) — not committed
│   ├── api/
│   │   └── routes.py             # All route handlers
│   ├── providers/
│   │   └── llm.py                # ChatNVIDIA client factory — retry+fallback chain (ADR-006)
│   ├── services/
│   │   ├── agent_service.py      # run_agent() — Orchestrator (default) + legacy ReAct loop, behind USE_ORCHESTRATOR flag
│   │   ├── calc_pipeline.py      # run_calc_pipeline() — deterministic BMR→TDEE→goal, no LLM
│   │   └── meal_parse_agent.py   # parse_meal() — isolated, evaluated meal-parsing LLM call
│   └── tools/
│       ├── bmr.py                # calculate_bmr()
│       ├── tdee.py               # calculate_tdee()
│       ├── calorie_goal.py       # calculate_calorie_goal()
│       └── meal_parser.py        # thin wrapper around services/meal_parse_agent.py
│
├── evals/                          # Accuracy harness for parse_meal_text (ADR-004) — see evals/README.md
│   ├── dataset/*.jsonl             # 70 golden examples across 5 categories
│   ├── run_eval.py                # scorer + --model (per-model comparison) + --gate (regression gate)
│   └── report/latest.json         # committed accuracy-over-time baseline
│
└── calai_frontend/                  # Flutter app (iOS/Android/web) — see calai_frontend/README.md
```

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
| `503` | NVIDIA NIM not reachable |
| `502` | NVIDIA NIM returned an unexpected HTTP error (e.g. every model in `LLM_MODELS` failed/rate-limited) |
| `500` | Agent hit MAX_STEPS without a final answer (legacy ReAct path only) |

---

## Tools Reference

| Tool | Calls LLM? | Implemented |
|------|-----------|-------------|
| `calculate_bmr` | No | Yes |
| `calculate_tdee` | No | Yes |
| `calculate_calorie_goal` | No | Yes |
| `parse_meal_text` | **Yes** (NVIDIA NIM, ADR-006) | Yes |
| `save_meal` | No | Coming — Step 5 |
| `get_daily_summary` | No | Coming — Step 6 |

**Activity levels:** `sedentary` · `lightly_active` · `moderately_active` · `very_active` · `extra_active`

**Goals:** `lose` · `maintain` · `gain`

---

## Configuration

`calai_backend/config.py` reads from environment (`calai_backend/.env` or shell) — see `.env.example`:

| Variable | Default | Description |
|----------|---------|-------------|
| `NVIDIA_API_KEY` | `""` | Required — NVIDIA NIM API key for the chat LLM provider. No local-model fallback. |
| `MAX_STEPS` | `8` | Iteration cap for the legacy ReAct loop only (`USE_ORCHESTRATOR=false`) |
| `USE_ORCHESTRATOR` | `true` | `true` → deterministic Orchestrator (default, faster); `false` → legacy ReAct loop |

`LLM_MODELS` (the NIM fallback chain, in order) is set in `config.py`, not via an env var — see its comment for the current chain and why it's 2 models rather than the 4 ADR-006 originally specified.

---

## Troubleshooting

**`401 Unauthorized` from NVIDIA NIM** — check two things, not just "is the key set": (1) `calai_backend/config.py` loads `.env` from `calai_backend/.env` specifically — a stale `.env` elsewhere in the repo can shadow it if `load_dotenv()` were ever changed back to its cwd-dependent default; (2) the variable name in `calai_backend/.env` must be exactly `NVIDIA_API_KEY` — `dotenv_values('calai_backend/.env').keys()` will show you the real name without printing the value.

**`410 Gone` from a specific model** — NVIDIA retires NIM-hosted models over time; the catalog's own `deprecated` flag has been found unreliable. Verify a model is actually live with `python evals/run_eval.py --model <name>` before relying on it, and see `config.py`'s comment on `LLM_MODELS` for the last verification.

**Agent stuck / max iterations** — Only applies on the legacy ReAct path (`USE_ORCHESTRATOR=false`); the default Orchestrator path has no iteration loop to get stuck in.

**Meal calories seem off** — `parse_meal_text` estimates from the LLM's training data, not a nutrition database lookup. Check `evals/report/latest.json`'s `calorie_mape_pct` for the current measured error rate before assuming a single bad estimate is representative — and if it's a genuine miss, add it to `evals/dataset/*.jsonl` as a permanent regression case (see `evals/README.md`).

---

## References

**Design record (`archdocs/`):**

| ADR | Decision |
|---|---|
| [ADR-001](archdocs/ADR-001-calai-architecture.md) | Initial architecture — tools, agent loop, FastAPI split from the learning-track CLI |
| [ADR-002](archdocs/ADR-002-react-agent-design.md) | ReAct agent design — the original single-loop tool-calling approach |
| [ADR-003](archdocs/ADR-003-multiagent-split.md) | Split the ReAct loop into a deterministic `Orchestrator` + `CalcPipeline` + `MealParseAgent` — 2.25x measured speedup, see [Why the Orchestrator is faster](#why-the-orchestrator-is-faster) |
| [ADR-004](archdocs/ADR-004-eval-harness.md) | The eval harness itself — why golden ranges, why 5 scoring dimensions, why this gates ADR-003 and every model/prompt change since |
| [ADR-005](archdocs/ADR-005-router-handler-registry.md) | Router → Handler Registry with bounded ReAct as escape hatch — proposed, mid-flight, not yet fully implemented |
| [ADR-006](archdocs/ADR-006-nvidia-nim-migration.md) | Full replacement of local Ollama with NVIDIA NIM — no rollback flag, fallback-chain design |

**Supporting evidence (`artefacts/`):**

- [`NOTES-orchestrator-vs-react.md`](artefacts/NOTES-orchestrator-vs-react.md) — the honest retrospective on ADR-003, including a second-pass self-review that corrects its own first-pass claims
- [`adr003-latency-comparison.json`](artefacts/adr003-latency-comparison.json) — raw timing data behind the 2.25x figure

**Process:**

- [`CLAUDE.md`](CLAUDE.md) — the multi-agent development workflow: agent ownership, pipeline sequencing, the review gate and fix-loop rules referenced in [How this codebase gets built](#how-this-codebase-gets-built)
- [`evals/README.md`](evals/README.md) — full eval harness usage: running it, reading a report, adding a new golden example, the `--model`/`--gate` flags
