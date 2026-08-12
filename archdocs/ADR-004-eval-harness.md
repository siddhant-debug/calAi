# ADR-004: Evaluation Harness for Meal-Parsing Accuracy

**Status:** Accepted — harness implemented and baseline run (steps 1-7, 10 done); CI wiring (step 8) not yet done
**Date:** 2026-08-01
**Deciders:** Siddhant Tomar
**Companions:** ADR-002 (defines `parse_meal_text`, the component under evaluation), ADR-003 (`MealParseAgent` is the extracted, isolated target this harness scores)

---

## Context

`parse_meal_text` (ADR-002, Tool 4) is the only nondeterministic component in the backend — it turns free text ("oats and 2 eggs") into structured `MealItem` records with `calories_kcal`, `protein_g`, `carbs_g`, `fat_g`, and a per-item `confidence`. Every other tool (`calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal`) is a pure formula; a unit test with a fixed input/output pair fully specifies correctness.

There is currently **no measurement of whether `parse_meal_text` is accurate**, at all:
- ADR-001's action items call for "Evaluate model accuracy on 20 common meal descriptions and tune system prompt" — never done.
- `AGENT-HANDOFF.md` and `calai_backend_review.md` both describe *bugs* in error handling around the LLM call, but nothing about whether the LLM's *output* is correct when it doesn't error.
- Changing the model (`qwen2.5:3b` → `qwen2.5:7b`, already done once per ADR-001), the prompt, or `format="json"` vs. tool-call-based extraction all currently ship with zero regression signal. The only feedback loop is "does it look right when I try it by hand."

**Why this is the highest-priority item in the project (per prior discussion):** the project's goal is demonstrable, evaluable AI engineering — not just a working demo. A demo can look impressive in a screen recording and still silently misparse half of ambiguous meals. An eval harness is the only artifact that turns "I built an LLM feature" into "I built an LLM feature and I can show you the accuracy number, and the commit where it went up."

---

## Decision

Build `evals/` as a standalone harness that scores `parse_meal_text` (soon `MealParseAgent`, ADR-003) against a golden dataset, runnable both locally (fast iteration) and in CI (regression gate).

### Scope: what gets evaluated

**In scope:** `parse_meal_text` only. It is the sole component whose output quality can vary run-to-run with no code change (model swap, prompt edit, temperature change).

**Explicitly out of scope:** `calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal` — these belong in `pytest` unit tests (deterministic input → exact expected output), not an eval harness. An eval harness implies "graded" correctness on a spectrum; a formula either matches its spec or it's a bug. Conflating the two would dilute what "eval" means in this project and is a common portfolio mistake worth explicitly avoiding.

### Directory structure

```
evals/
├── dataset/
│   └── meals.jsonl              # golden examples: input text → expected structured output
├── scorers/
│   ├── item_match.py            # did we extract the right food items (name/quantity match)?
│   ├── calorie_accuracy.py      # numeric tolerance scoring vs. expected calories/macros
│   └── confidence_calibration.py # do low-confidence flags correlate with actual errors?
├── run_eval.py                  # loads dataset, calls parse_meal_text, scores, writes report
├── report/
│   └── latest.json              # last run's scores, committed or gitignored — see below
└── README.md                    # how to add a golden example, how to read a report
```

### Golden dataset format

```jsonl
{"input": "2 eggs and a slice of toast", "meal_type": "breakfast", "expected_items": [{"name": "egg", "quantity": 2, "unit": "whole", "calories_kcal_range": [130, 160]}, {"name": "toast", "quantity": 1, "unit": "slice", "calories_kcal_range": [65, 90]}], "expected_total_kcal_range": [195, 250]}
```

**Why ranges, not exact values:** food calorie counts are inherently fuzzy (a "large egg" vs. "medium egg" differ) — grading against a single exact number would make the harness reject correct-but-differently-rounded answers as failures. Ranges sourced from USDA FoodData Central (already a reference in ADR-001) keep grading honest without demanding false precision.

**Seed set:** start with the 20 meals ADR-001's action item already called for, expand incrementally whenever a real parse failure is found in manual testing — every bug becomes a permanent regression-test case, same principle as adding a unit test for every bug fix.

### Scoring dimensions (per example, then aggregated)

1. **Item recall/precision** — did we find the right foods, not too few, not hallucinated extras?
2. **Quantity/unit correctness** — "2 eggs" vs "1 egg", "80g" vs "80oz" (unit confusion is a realistic small-model failure mode)
3. **Calorie/macro accuracy** — within the expected range, scored as pass/fail per item plus an aggregate mean-absolute-percentage-error for a trend metric across runs
4. **Confidence calibration** — when the model flags `confidence: "low"`, is it actually more often wrong on those items than on `"high"`-confidence ones? (Validates that confidence is a meaningful signal, not decorative — this feeds directly into ADR-003's plan to gate persistence on confidence.)
5. **Format validity** — did it produce parseable JSON matching the `MealParseResponse` Pydantic schema at all, before any accuracy scoring happens (a hard pass/fail gate; a validity failure short-circuits the other four scores)

### Report format

All score fields are on a 0-100 percentage scale (including per-item `pct_error` inside `failures[]`), matching `format_valid_pct`'s convention — no field is a raw 0-1 fraction:

```json
{
  "run_at": "2026-08-01T14:32:00Z",
  "model": "qwen2.5:3b",
  "n_examples": 20,
  "format_valid_pct": 100.0,
  "item_precision_pct": 91.0,
  "item_recall_pct": 87.0,
  "calorie_mape_pct": 8.4,
  "confidence_calibration_score_pct": 76.0,
  "failures": [
    {"input": "a bowl of cereal", "reason": "quantity_missing", "expected": "...", "got": "..."}
  ]
}
```

Committing `report/latest.json` to git (not gitignoring it) is intentional — the git history of this one file *is* the accuracy timeline, and it's the artifact you'd screenshot for a resume/portfolio: "accuracy over time as the model/prompt changed."

---

## Options Considered

### Option A: Manual spot-checking (status quo)
Try a few meals by hand, eyeball the output, ship if it looks reasonable.

| Dimension | Assessment |
|---|---|
| Effort | None (already the current approach) |
| Regression detection | None — a prompt change that silently degrades accuracy ships unnoticed |
| Resume value | None — "I checked it manually" isn't a claim, it's an admission |

**Rejected** — this is what's being replaced.

### Option B: Use an existing eval framework (e.g. `promptfoo`, `deepeval`, LangSmith evals)
Adopt a third-party eval tool wired to the existing LangSmith tracing already present in `calai_agent.py` (per `AGENT-HANDOFF.md` — `@traceable` decorators, currently disabled pending API key confirmation).

| Dimension | Assessment |
|---|---|
| Effort | Lower initial setup for standard metrics |
| Control over domain-specific scoring | Lower — calorie-range tolerance and confidence calibration are project-specific, would still need custom scorers on top |
| Dependency footprint | New — another package/service on a project that's explicitly local-first (ADR-001) |
| Resume narrative | Weaker — "I plugged in a tool" vs. "I designed the scoring methodology" |

**Rejected for now, revisit later:** the custom scorers needed (calorie ranges, confidence calibration) aren't off-the-shelf regardless of framework, so the framework saves less than it looks like. LangSmith tracing (already partially wired) is worth re-enabling separately as an observability layer, orthogonal to this harness — that's a "revisit later," not blocking.

### Option C: Custom lightweight harness (`evals/`) ✅ (Chosen)
As described in Decision above — plain Python, no new runtime dependency beyond what's already in `requirements.txt` (`pydantic` for schema validation is already there).

| Dimension | Assessment |
|---|---|
| Effort | Medium — dataset curation is the real cost, harness code is a few hundred lines |
| Control | Full — scorers match the actual product risk (wrong calories, miscalibrated confidence) |
| Resume narrative | Strongest — demonstrates eval design, not just eval usage |
| CI-ready | Yes — `run_eval.py` is a script with a nonzero exit code on regression, trivially wired to a git hook or CI step |

---

## Non-Goals

- Not building a UI/dashboard for eval results — `report/latest.json` + git history is sufficient at this scale.
- Not evaluating latency here — that's covered separately by the timing already required in `ai-engineer`'s conventions (`time.perf_counter()` around every LLM call, per `.claude/agents/ai-engineer.md`) and by ADR-003's before/after comparison.
- Not building synthetic/generated golden data via another LLM call — seed examples are hand-written or sourced from USDA data specifically to avoid the eval set inheriting the same model's blind spots it's meant to catch.

---

## Consequences

**Becomes easier:**
- Any prompt/model change (already a recurring event — `qwen2.5:3b` → `7b`) gets an objective before/after number instead of a vibe check.
- ADR-003's orchestrator migration has a concrete parity gate ("new `MealParseAgent` must score ≥ current baseline") instead of "seems fine."
- Bug reports become permanent regression tests — every real failure found by hand gets added to `dataset/meals.jsonl`.

**Becomes harder:**
- Golden dataset maintenance — ranges need occasional revisiting as USDA data or product scope (new food types) changes.
- Test run time — each eval run makes N real LLM calls (no mocking the model, since the model's actual output is what's under test), so `run_eval.py` will be slow (minutes, given the ~140s single-call latency noted in ADR-002/ADR-003) unless run against a faster model or a remote/GPU Ollama instance. Budget for this in CI — likely run on a schedule or on-demand, not on every commit, until latency improves.

**Revisit later:**
- Re-enable LangSmith tracing (`@traceable`, currently disabled per `AGENT-HANDOFF.md`) as a complementary observability layer once the API key is confirmed working — traces answer "what happened on this one request," evals answer "how good are we on average," both useful but not the same tool.
- If dataset grows past ~100 examples, consider sampling a subset for fast local iteration and running the full set only in CI.

---

## Action Items

1. [x] Create `evals/` directory structure as specified above — `dataset/`, `scorers/`, `run_eval.py`, `report/`, `README.md`
2. [x] Write seed examples in `dataset/*.jsonl` — 33 unique examples across `meals.jsonl`, `north_indian.jsonl`, `south_indian.jsonl`, `snacks.jsonl` (split into categories rather than one flat 20-item file; an earlier 7-example accidental-duplicate bug across files was found and fixed before the baseline run)
3. [x] Implement `run_eval.py` — loads every dataset file, calls `parse_meal_text` per example, isolates per-example failures so one bad call doesn't kill the run, aggregates and writes reports
4. [x] Implement `scorers/item_match.py` (fuzzy precision/recall on extracted items)
5. [x] Implement `scorers/calorie_accuracy.py` (range pass/fail + MAPE, referenced to range midpoint)
6. [x] Implement `scorers/confidence_calibration.py` — done, but the real result is a **negative finding**: calibration score is 39.6% (below the 50% no-signal midpoint) against the current baseline, i.e. confidence is currently an inverted signal, not yet a usable one (see below)
7. [x] Run baseline eval, commit `report/latest.json` as the first data point — real run against `qwen2.5:3b` (the only model actually reachable; `config.py` defaults to `7b`, which is not pulled anywhere live), 33 examples, ~14 min wall-clock. Result: 100% format validity, 83.6% item precision, 92.0% item recall, 59.3% calorie MAPE, 39.6% confidence calibration. All report fields are 0-100 percentages with `_pct`-suffixed keys.
8. [ ] Wire `run_eval.py` into a manual/CI step with a regression threshold — not started
9. [ ] Use this baseline as the gate for ADR-003 step 4 (extraction parity check) and step 7 (orchestrator rewrite comparison) — baseline exists and is ready to use, but ADR-003's code split hasn't started yet
10. [x] Document in `evals/README.md` how to add a new golden example when a real-world parse failure is found
