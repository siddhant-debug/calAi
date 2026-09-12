# CalAI Eval Harness

Scores `parse_meal_text` (`calai_backend/tools/meal_parser.py`) — the only
nondeterministic component in the backend — against a golden dataset of
meal descriptions. See `archdocs/ADR-004-eval-harness.md` for the full
design rationale; this README is just the "how to use it" reference.

Deterministic tools (`calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal`)
are **not** covered here — they belong in `calai_backend/tests/` as plain
pytest unit tests, since a formula either matches its spec or it's a bug,
not a graded-accuracy question.

## Dataset layout

`dataset/` holds multiple golden sets, one `.jsonl` file per category, so
accuracy can be tracked per cuisine/meal-category as well as overall:

| File | Contents |
|---|---|
| `dataset/meals.jsonl` | General/mixed meals (Western + a few Indian dishes) |
| `dataset/north_indian.jsonl` | North Indian dishes, spread across breakfast/lunch/dinner/snack |
| `dataset/south_indian.jsonl` | South Indian dishes, spread across breakfast/lunch/dinner/snack |
| `dataset/snacks.jsonl` | Snack-specific foods (Indian and Western), all `meal_type: "snack"` |
| `dataset/western_and_desserts.jsonl` | Desserts, beverages, and Western dishes not covered by `meals.jsonl` |

70 examples total across the 5 files as of the ADR-006 dataset expansion — up
from the original 33, to reduce how much a single wrong parse swings the
aggregate `_pct` metrics (with 33 examples, one flip moved a metric by ~3
points, which made `--gate` noisy).

Each file is independent — add a new one (e.g. `dataset/east_indian.jsonl`)
and it's automatically picked up the next time `run_eval.py` runs in its
default directory mode.

## Running the eval

```bash
cd /Users/siddhanttomar/Claude/Projects/calAi
source .venv/bin/activate
cd evals
python run_eval.py
```

By default this runs **every** `.jsonl` file in `dataset/` (directory mode).
For each dataset file it:
1. Loads the examples.
2. Calls the real `parse_meal_text` (a real NVIDIA NIM call — the
   `calai_backend/config.py`/`LLM_MODELS` retry+fallback chain, ADR-006, no
   mocking — the model's actual output is what's under test) for every
   example.
3. Scores each example against `scorers/item_match.py`,
   `scorers/calorie_accuracy.py`, and `scorers/confidence_calibration.py`.
4. Writes that dataset's own report to `report/<dataset_stem>.json`
   (e.g. `report/north_indian.json`).

After all datasets finish, every example from every dataset is pooled
together into one combined report at `report/latest.json` — this is the
single top-line number; the per-dataset files are the breakdown by category.

This is slow — each `parse_meal_text` call is a real LLM round trip (roughly
15-70s depending on item count and model, see the "actual measured timings"
note in each report's `wall_clock_s`), so running all datasets takes several
minutes to tens of minutes depending on dataset size. That's expected; don't
try to speed this up by mocking the model.

Run a single category instead of everything:

```bash
python run_eval.py --dataset dataset/north_indian.jsonl
# writes only the combined report (default report/latest.json); no
# per-dataset file is written in single-file mode since there's nothing to
# break down
```

Override output locations:

```bash
python run_eval.py --dataset dataset --out report/latest.json
```

### Scoring one model in isolation

The default run scores whatever `config.LLM_MODELS` fallback chain is
currently configured — it doesn't tell you how any *one* model in that
chain performs on its own. `--model` temporarily overrides the chain to a
single model for the run and writes to its own report file instead of
touching `report/latest.json`:

```bash
python run_eval.py --model openai/gpt-oss-20b
# writes report/openai_gpt-oss-20b.json — report/latest.json is untouched
```

Use this before adding a candidate model to the fallback chain — verify it
actually responds (NVIDIA's own catalog `deprecated` flag has been found
unreliable; several models it lists as live return `410 Gone` on a real
call) and see how it scores, rather than assuming a same-vendor model is
a safe swap.

### Gating a run against the baseline

`--gate` turns a run into a pass/fail check instead of a number you have to
eyeball:

```bash
python run_eval.py --gate --baseline report/latest.json --tolerance-pct 5.0
```

Compares every `_pct`-suffixed field in the new run against the baseline
report and exits `1` if any of them regressed beyond `--tolerance-pct`
(lower-is-better for `calorie_mape_pct`, higher-is-better for everything
else). A missing/unreadable baseline is treated as "nothing to compare,"
not a failure. `reviewer` uses this — not a manual JSON diff — to gate any
change to `parse_meal_text`'s prompt or model.

## Reading `report/latest.json`

```json
{
  "run_at": "2026-09-12T19:44:59Z",
  "model": ["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", "openai/gpt-oss-20b"],
  "n_examples": 70,
  "format_valid_pct": 100.0,
  "item_precision_pct": 91.2,
  "item_recall_pct": 99.0,
  "calorie_mape_pct": 37.1,
  "confidence_calibration_score_pct": 57.1,
  "confidence_calibration_detail": { "...": "per-confidence-bucket error rates" },
  "failures": [ { "input": "...", "reason": "...", "expected": "...", "got": "..." } ],
  "total_wall_clock_s": 1397.3,
  "datasets": ["meals.jsonl", "north_indian.jsonl", "south_indian.jsonl", "snacks.jsonl", "western_and_desserts.jsonl"],
  "per_dataset_summary": { "north_indian": { "item_precision_pct": 93.8, "...": "..." } }
}
```

Every field ending in `_pct` (including per-item `pct_error` inside
`failures[].out_of_range_items[]`) is on a **0-100 scale**, not a 0-1
fraction — e.g. `"calorie_mape_pct": 8.4` means 8.4% error, and a
per-item `"pct_error": 66.7` means that one item's estimate was 66.7% off
from the expected range's midpoint. This matches `format_valid_pct`, which
was always 0-100.

`datasets` and `per_dataset_summary` only appear in the **combined**
report (`report/latest.json` when run in directory mode) — they list which
dataset files contributed and give each one's headline numbers so you can
spot a category-specific regression (e.g. "south Indian accuracy dropped but
north Indian didn't") without opening every per-dataset report file.

`model` reports the configured `LLM_MODELS` fallback chain (read from
`calai_backend.config.LLM_MODELS` at run time), not which specific model in
the chain answered any given call — NIM's retry+fallback wrapping
(ADR-006) doesn't currently surface per-call "which model answered" back to
the caller. Which one actually fires per request is currently only
observable via manual inspection (e.g. a smoke test against a rate-limited
primary), not via this report.

- **`format_valid_pct`** — hard gate: did the model return parseable JSON
  matching the expected shape at all? A format failure short-circuits the
  other four scores for that example (see `run_eval.py::run_example`).
- **`item_precision_pct` / `item_recall_pct`** — fuzzy name-match
  (substring/token overlap, see `scorers/item_match.py`) across all examples
  pooled together, not averaged per-example, on a 0-100 scale. "Precision" =
  of the items the model extracted, how many were real; "recall" = of the
  real items, how many were found.
- **`calorie_mape_pct`** — mean absolute percentage error (0-100 scale),
  computed only over matched items, using each expected item's
  `calories_kcal_range` midpoint as the reference value. `null` if no items
  matched at all.
- **`confidence_calibration_score_pct`** — in `[0, 100]`. `100.0` = perfect
  (items the model flags `"low"` confidence are wrong more often than
  `"high"` ones); `50.0` = no signal or insufficient data; `0.0` = inverted
  (low confidence is *more* often right than high — actively misleading).
  `null` if the run didn't produce matched items at both `"high"` and
  `"low"` confidence to compare.
- **`failures`** — every example that either failed format validation,
  missed an expected item, or produced an out-of-range calorie estimate.
  This list is the primary debugging tool after a run — read it before
  looking at the aggregate numbers.

`report/latest.json` is committed to git (not gitignored). Its git history
*is* the accuracy timeline — each commit that changes the prompt, the model,
or `format="json"` behavior should be followed by a re-run and a new commit
of this file, so `git log -p evals/report/latest.json` tells the story of
how accuracy moved over time.

## Adding a new golden example

Every real-world parse failure found by hand (via `/api/parse-meal`, the
agent, or manual testing) should become a permanent regression-test case —
same principle as adding a unit test for every bug fix.

1. Reproduce the failure — note the exact input text and `meal_type` used.
2. Look up realistic calorie ranges for the food(s) involved (USDA
   FoodData Central is the reference source used for the seed dataset;
   ranges, not single values, since "large egg" vs "medium egg" legitimately
   differ — see ADR-004's rationale).
3. Append one line to the dataset file that best fits the failure's category
   (`dataset/north_indian.jsonl`, `dataset/south_indian.jsonl`,
   `dataset/snacks.jsonl`, or `dataset/meals.jsonl` for anything general) in
   this format:

```json
{"input": "<the exact text that failed>", "meal_type": "breakfast|lunch|dinner|snack", "expected_items": [{"name": "food name", "quantity": <number>, "unit": "piece/g/cup/etc", "calories_kcal_range": [<low>, <high>]}], "expected_total_kcal_range": [<low>, <high>]}
```

   If the failure is a whole new category (a cuisine with no existing file),
   create a new `dataset/<category>.jsonl` — it's picked up automatically by
   the default directory-mode run, no code change needed.

4. Re-run `python run_eval.py` and confirm the new example shows up (pass
   or fail) in both that category's `report/<category>.json` and the
   combined `report/latest.json` — a failing new example is expected and
   fine; it's now tracked instead of silently reoccurring.
5. Commit the dataset change and the updated report file(s) together, so
   each report always reflects the dataset it was scored against.

## Files

| File | Purpose |
|---|---|
| `dataset/meals.jsonl` | General/mixed golden examples |
| `dataset/north_indian.jsonl` | North Indian dishes across all meal types |
| `dataset/south_indian.jsonl` | South Indian dishes across all meal types |
| `dataset/snacks.jsonl` | Snack-specific foods |
| `dataset/western_and_desserts.jsonl` | Desserts, beverages, Western dishes |
| `scorers/item_match.py` | Fuzzy precision/recall on extracted item names |
| `scorers/calorie_accuracy.py` | Per-item calorie-range pass/fail + aggregate MAPE |
| `scorers/confidence_calibration.py` | Does `confidence: "low"` correlate with actually being wrong? |
| `run_eval.py` | Loads dataset(s), calls `parse_meal_text` per example, aggregates, writes per-dataset + combined reports |
| `report/latest.json` | Combined (all-dataset) scores for the current fallback chain — committed to git as the accuracy timeline |
| `report/<dataset_stem>.json` | Per-category scores (e.g. `report/north_indian.json`) |
| `report/<model_name>.json` | Single-model scores from `--model <name>` (e.g. `report/openai_gpt-oss-20b.json`) — used to vet a candidate fallback model before adding it to `config.LLM_MODELS` |
| `report/archive/` | Superseded baselines kept for the accuracy-over-time story when `latest.json` is about to be overwritten by an incompatible run (different provider/dataset size) |

## Known scope limits (see ADR-004 "Non-Goals")

- No UI/dashboard — `report/latest.json` + git history is the artifact.
- Latency is not scored here — that's covered by the `time.perf_counter()`
  logging already required around every LLM call
  (`.claude/agents/ai-engineer.md`).
- Not wired into CI yet — ADR-004 action item 8, future work.
- Quantity/unit correctness (e.g. "2 eggs" vs "1 egg") is not yet a
  dedicated scorer — the dataset captures it in `expected_items[].quantity`
  and `.unit`, but no scorer currently checks it. Worth adding as a
  follow-up if the model's item-count/portion accuracy needs its own signal
  beyond what `calorie_accuracy`'s range check indirectly captures.
