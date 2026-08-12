"""Confidence calibration scorer.

Validates that the model's per-item `confidence` field ("high"/"medium"/"low")
is a meaningful signal rather than decorative: items the model flags as
low-confidence should be wrong (i.e. calorie estimate outside the golden
range) more often than items it flags as high-confidence.

Requires `MealItem.confidence` (added to `calai_backend/schemas.py` and the
extraction prompt in `calai_backend/tools/meal_parser.py` alongside this
harness — see evals/README.md for why).

How this file works, in order:
1. `score_confidence_calibration` is called once, at the very end of a run
   (from `run_eval.py::aggregate`), with the flattened matched-item records
   from *every* example pooled together — calibration is a run-level signal,
   not something meaningful per single example.
2. Items are bucketed by their `confidence` label ("low"/"medium"/"high");
   within each bucket we track whether the item's calorie estimate was
   actually wrong (outside the golden range).
3. Per-bucket error rates are computed (fraction wrong within that bucket).
4. The two extremes ("low" vs "high") are compared: if low-confidence items
   are wrong more often than high-confidence ones, that's a well-calibrated
   confidence signal. That difference is rescaled into a single 0-100 score
   (see docstring below) so it reads on the same scale as every other
   `_pct` field in the report.
"""

from __future__ import annotations

from typing import Any

CONFIDENCE_LEVELS = ("low", "medium", "high")


def score_confidence_calibration(item_records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    item_records: flat list across the whole run, one entry per matched item:
        {"confidence": "high"|"medium"|"low"|None, "in_range": bool}

    Returns per-bucket error rates and a single calibration_score in [0, 100]
    (percentage scale, matching every other `_pct` field in the report):
      100.0 = perfect calibration (low-confidence items are always wrong,
              high-confidence items are always right)
      50.0  = no signal (error rate identical across confidence levels, or
              insufficient data to tell)
      0.0   = inverted calibration (low-confidence items are *more* often
              correct than high-confidence ones — confidence is actively
              misleading)
    """
    # Step 1: bucket every matched item by its stated confidence, tracking
    # only whether it was wrong (True) or right (False) in that bucket.
    buckets: dict[str, list[bool]] = {level: [] for level in CONFIDENCE_LEVELS}
    unlabeled = 0

    for rec in item_records:
        conf = rec.get("confidence")
        in_range = rec.get("in_range")
        if conf not in CONFIDENCE_LEVELS or in_range is None:
            unlabeled += 1
            continue
        buckets[conf].append(not in_range)  # True = wrong

    # Step 2: per-bucket error rate (0-1 fraction — these stay unscaled since
    # they're diagnostic detail, not the headline metric; see README).
    error_rates: dict[str, float | None] = {}
    counts: dict[str, int] = {}
    for level in CONFIDENCE_LEVELS:
        vals = buckets[level]
        counts[level] = len(vals)
        error_rates[level] = (sum(vals) / len(vals)) if vals else None

    high_err = error_rates["high"]
    low_err = error_rates["low"]

    if high_err is None or low_err is None:
        # Not enough data across both extremes to judge calibration.
        calibration_score = None
        note = "insufficient data: need matched items at both 'high' and 'low' confidence"
    else:
        # Step 3: (low_err - high_err) naturally falls in [-1, 1] — positive
        # means low-confidence is wrong more often (good calibration),
        # negative means inverted. Rescale to [0, 100] so 50.0 is the
        # "no signal" midpoint and the value reads as a percentage like
        # every other score in the report.
        calibration_score = round(100.0 * (low_err - high_err + 1) / 2, 1)
        note = None

    return {
        "error_rate_by_confidence": error_rates,
        "n_items_by_confidence": counts,
        "n_unlabeled_or_unmatched": unlabeled,
        "calibration_score": calibration_score,
        "note": note,
    }
