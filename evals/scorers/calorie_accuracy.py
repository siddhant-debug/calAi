"""Calorie accuracy scorer: per-item range pass/fail plus aggregate MAPE.

Reference value for MAPE is the midpoint of each expected item's
calories_kcal_range (per ADR-004), since ranges (not single values) are the
ground truth.

How this file works, in order:
1. `score_calories` is called once per example (from `run_eval.py`) with the
   golden `expected_items` and the model's `got_items` for that example.
2. It re-derives the same fuzzy name-alignment `run_eval.py` already used
   (`match_items`) rather than being handed the pairing directly, so this
   scorer is self-contained and testable on its own.
3. For each matched (expected, got) pair, it checks whether the model's
   `calories_kcal` falls inside the golden `calories_kcal_range`, and
   computes a percent error against the midpoint of that range.
4. Unmatched expected items are skipped here on purpose — they're already
   penalized via `item_match.py`'s recall, so scoring "no prediction" against
   a calorie range would double-count the same miss.
5. Returns per-item detail (`per_item`) plus a couple of example-level
   summary numbers (`range_pass_rate`, `mape`) that `run_eval.py::aggregate`
   pools across the whole run.

All percentage-shaped values here (`pct_error`, `mape`) are on a 0-100 scale,
e.g. `66.7` means 66.7% error — not `0.667`. This matches `format_valid_pct`
and every other `_pct` field in the report; see evals/README.md.
"""

from __future__ import annotations

from typing import Any

from evals.scorers.item_match import match_items


def _midpoint(range_: list[float]) -> float:
    lo, hi = range_
    return (lo + hi) / 2.0


def score_calories(expected_items: list[dict[str, Any]], got_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Score calorie accuracy for one example.

    Only matched items (per item_match's fuzzy alignment) are scored for
    range pass/fail and contribute to MAPE — an unmatched expected item is
    already penalized by item_match's recall, and scoring "no prediction"
    against a calorie range would just be double-counting the same miss.
    """
    # Step 1: re-derive the fuzzy expected<->got alignment for this example.
    match = match_items(expected_items, got_items)

    per_item_results = []
    abs_pct_errors = []

    # Step 2: for every matched pair, check range membership and percent
    # error against the golden range's midpoint (the range itself has no
    # single "true" value, so the midpoint is the best single reference
    # point for a continuous error metric — see ADR-004).
    for exp_idx, got_idx in match["pairs"]:
        exp = expected_items[exp_idx]
        got = got_items[got_idx]
        lo, hi = exp["calories_kcal_range"]
        got_kcal = got.get("calories_kcal")

        in_range = got_kcal is not None and lo <= got_kcal <= hi
        mid = _midpoint(exp["calories_kcal_range"])
        # 0-100 scale (percentage points), not a 0-1 fraction — see module
        # docstring. `None` only when the model omitted calories_kcal.
        pct_error = (
            round(100.0 * abs(got_kcal - mid) / mid, 1)
            if (got_kcal is not None and mid)
            else None
        )

        per_item_results.append({
            "name": exp.get("name"),
            "expected_range": exp["calories_kcal_range"],
            "got_kcal": got_kcal,
            "in_range": in_range,
            "pct_error": pct_error,
        })
        if pct_error is not None:
            abs_pct_errors.append(pct_error)

    # Step 3: example-level summary (range_pass_rate/mape) — informational;
    # run_eval.py::aggregate pools abs_pct_errors itself across every
    # example rather than averaging these per-example means, so a single
    # example's item count doesn't get over/under-weighted in the final
    # calorie_mape_pct.
    n_matched = len(per_item_results)
    n_in_range = sum(1 for r in per_item_results if r["in_range"])
    range_pass_rate = n_in_range / n_matched if n_matched else 0.0
    mape = sum(abs_pct_errors) / len(abs_pct_errors) if abs_pct_errors else None

    return {
        "per_item": per_item_results,
        "range_pass_rate": range_pass_rate,
        "mape": mape,  # already 0-100 scale, since pct_error is
        "n_matched": n_matched,
    }
