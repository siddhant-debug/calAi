"""Item-match scorer: precision/recall on extracted food item names.

Matching is fuzzy on purpose — "egg" should match "eggs", "grilled chicken"
should match "grilled chicken breast" — because the model under test is not
expected to reproduce the golden dataset's exact wording, only to identify
the same foods. We use case-insensitive singular-stripped substring overlap
in both directions.

How this file works, in order:
1. `match_items` is called once per example (from `run_eval.py` directly,
   and again internally by `calorie_accuracy.py` to get the same alignment)
   with the golden `expected_items` and the model's `got_items`.
2. Names are normalized (`_normalize`) — lowercased, whitespace-trimmed,
   crudely singularized — then greedily matched name-by-name via
   `_fuzzy_match` (exact match, substring either direction, or token
   overlap) so wording differences don't count as misses.
3. Matching is greedy, one-to-one: each got-item can satisfy at most one
   expected-item, in expected-item order, so an example with "rice" and
   "fried rice" is not scored twice against a single got-item match.
4. Returns the per-example precision/recall/f1 (used for local debugging;
   `run_eval.py::aggregate` recomputes precision/recall pooled across the
   *whole run* rather than averaging these per-example values, so a small
   example's noise doesn't get equal weight to a large one) plus the raw
   (expected_idx, got_idx) `pairs` that `calorie_accuracy.py` reuses to
   avoid re-deriving the same alignment twice.

Note: the `precision`/`recall`/`f1` values returned here stay on a 0-1
scale — they're per-example internal detail, not written to the report
directly. The report's headline `item_precision_pct`/`item_recall_pct`
(see `run_eval.py::aggregate`) are pooled across all examples and are on
the 0-100 scale.
"""

from __future__ import annotations

from typing import Any


def _normalize(name: str) -> str:
    name = name.strip().lower()
    # crude singularization so "eggs" <-> "egg" matches
    if name.endswith("ies") and len(name) > 3:
        name = name[:-3] + "y"
    elif name.endswith("es") and len(name) > 3:
        name = name[:-2]
    elif name.endswith("s") and not name.endswith("ss") and len(name) > 2:
        name = name[:-1]
    return name


def _fuzzy_match(a: str, b: str) -> bool:
    """True if the normalized names overlap enough to be considered the same food."""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    # token overlap fallback, e.g. "chicken breast" vs "grilled chicken"
    ta, tb = set(na.split()), set(nb.split())
    return bool(ta & tb)


def match_items(expected_items: list[dict[str, Any]], got_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Greedy one-to-one fuzzy match between expected and got item name lists.

    Returns a dict with precision, recall, f1, and the matched/unmatched
    index pairs so calorie_accuracy.py can reuse the alignment.
    """
    expected_names = [item.get("name", "") for item in expected_items]
    got_names = [item.get("name", "") for item in got_items]

    matched_expected_idx: set[int] = set()
    matched_got_idx: set[int] = set()
    pairs: list[tuple[int, int]] = []

    # Greedy alignment: walk expected items in order, claim the first
    # unclaimed got-item that fuzzy-matches. Not globally optimal (a
    # different assignment could occasionally match more pairs), but
    # simple, deterministic, and good enough at this dataset's scale.
    for i, exp_name in enumerate(expected_names):
        for j, got_name in enumerate(got_names):
            if j in matched_got_idx:
                continue
            if _fuzzy_match(exp_name, got_name):
                matched_expected_idx.add(i)
                matched_got_idx.add(j)
                pairs.append((i, j))
                break

    true_positives = len(pairs)
    n_expected = len(expected_items)
    n_got = len(got_items)

    precision = true_positives / n_got if n_got else (1.0 if n_expected == 0 else 0.0)
    recall = true_positives / n_expected if n_expected else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positives": true_positives,
        "n_expected": n_expected,
        "n_got": n_got,
        "pairs": pairs,  # list of (expected_idx, got_idx)
        "unmatched_expected": [expected_names[i] for i in range(n_expected) if i not in matched_expected_idx],
        "unmatched_got": [got_names[j] for j in range(n_got) if j not in matched_got_idx],
    }
