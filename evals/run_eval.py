"""Eval harness runner for `parse_meal_text` (calai_backend/tools/meal_parser.py).

Usage:
    cd evals
    python run_eval.py                                   # run every *.jsonl in dataset/
    python run_eval.py --dataset dataset/north_indian.jsonl   # run a single category
    python run_eval.py --dataset dataset --out report/latest.json

`--dataset` may point to a single `.jsonl` file or (default) a directory of
them. In directory mode, every dataset file gets its own scored report at
`report/<dataset_stem>.json`, and all examples across every dataset are also
pooled into one combined report (default `report/latest.json`) so there is
still a single top-line accuracy number in addition to the per-category
breakdown.

Per-example failures (malformed JSON, invalid meal_type, connection errors)
are caught and recorded as `format_valid: False` failures rather than
crashing the whole run.

How this file works, in order:
1. `resolve_dataset_paths` figures out which `.jsonl` file(s) to run —
   either the single file passed via `--dataset`, or (default) every
   `.jsonl` file found in `dataset/`.
2. `load_dataset` reads one file into a list of example dicts (one JSON
   object per line).
3. `run_example` calls the real `parse_meal_text` for one example, on a
   worker thread with a hard timeout so one hung Ollama call can't stall
   the whole run indefinitely (see PER_CALL_TIMEOUT_S). Any exception or
   timeout is caught here and turned into a `format_valid: False` result —
   this is the per-example isolation boundary: one bad example never
   crashes `main()`.
4. Each successful call is scored against the golden `expected_items` via
   `scorers/item_match.py` (fuzzy name precision/recall) and
   `scorers/calorie_accuracy.py` (per-item calorie-range pass/fail + percent
   error), and a flat "matched item" record (confidence + in_range) is
   built for the calibration scorer.
5. `run_dataset` runs every example in one file sequentially and times the
   whole file's wall clock.
6. `aggregate` pools every example's results — format-valid rate, pooled
   precision/recall, mean calorie percent error, and confidence calibration
   (`scorers/confidence_calibration.py`) — into one report dict, plus a
   `failures` list of every example that didn't fully pass (the primary
   debugging artifact).
7. `main()` ties it together: run each dataset file, write its own
   per-dataset report (directory mode only), pool *all* examples across
   *all* datasets into one combined report, and write that to
   `report/latest.json` (or `--out`).

All percentage-shaped fields in reports (anything ending in `_pct`,
including per-item `pct_error`) are on a 0-100 scale, not 0-1 — see
evals/README.md's report-field glossary.

ADR-005 Known Limitations item 2 (eval-parity gap): everything above this
paragraph is the ORIGINAL harness, which calls `parse_meal_text` directly —
it proves `parse_meal_text` itself hasn't regressed, but (before ADR-005)
production actually fed `parse_meal` the LLM-reworded `meal_text` from
`extract_request_fields`, not the user's raw words, so that "parity" score
said nothing about end-to-end production accuracy. `--orchestrator-subset N`
below is the fix for that gap: it takes the first N already-scored,
format-valid examples and re-runs them through the REAL production entry
point (`calai_backend.services.agent_service._run_agent_orchestrator`), not
a reimplementation of its logic, and reports the orchestrator-path score
next to the direct-path score for the same inputs. See
`run_example_via_orchestrator`'s docstring for the exact mechanism. This is
opt-in (default 0 = skipped) so the default `python run_eval.py` invocation
and its committed baseline (`report/latest.json`) are unaffected — the
orchestrator check writes its own separate report,
`report/orchestrator_parity.json`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from calai_backend.config import MODEL_NAME  # noqa: E402
from calai_backend.services import agent_service  # noqa: E402
from calai_backend.tools.meal_parser import parse_meal_text  # noqa: E402
from evals.scorers.calorie_accuracy import score_calories  # noqa: E402
from evals.scorers.confidence_calibration import score_confidence_calibration  # noqa: E402
from evals.scorers.item_match import match_items  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("calai.evals")

# Observed per-call latency for qwen2.5:3b has ranged ~15-70s across prior
# runs. 180s (~3x the slowest observed call) gives real slow calls room to
# finish while still bounding a single hung Ollama call from stalling the
# entire run indefinitely (this happened once — a run silently stopped
# making progress for 600s+ with no report ever written).
PER_CALL_TIMEOUT_S = 180.0


def load_dataset(path: Path) -> list[dict[str, Any]]:
    examples = []
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))
    return examples


def run_example(example: dict[str, Any], timeout_s: float = PER_CALL_TIMEOUT_S) -> dict[str, Any]:
    """Run parse_meal_text on one example and score it. Never raises, and never
    blocks the run past `timeout_s` — a hung Ollama call is recorded as a
    timeout failure and the run moves on to the next example rather than
    stalling indefinitely (see PER_CALL_TIMEOUT_S comment)."""
    meal_text = example["input"]
    meal_type = example.get("meal_type", "snack")

    t0 = time.perf_counter()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(parse_meal_text, meal_text, meal_type)
    try:
        result = future.result(timeout=timeout_s)
        elapsed = time.perf_counter() - t0
        log.info("[run_example] %.2fs  input=%r", elapsed, meal_text)
    except concurrent.futures.TimeoutError:
        elapsed = time.perf_counter() - t0
        log.error(
            "[run_example] TIMEOUT after %.1fs (limit %.0fs)  input=%r — "
            "abandoning this call and moving to the next example. The "
            "underlying LLM call may keep running in the background until "
            "it eventually completes or the process exits (Python threads "
            "can't be forcibly killed).",
            elapsed, timeout_s, meal_text,
        )
        return {
            "input": meal_text,
            "format_valid": False,
            "elapsed_s": elapsed,
            "reason": "timeout",
            "error": f"parse_meal_text exceeded {timeout_s:.0f}s timeout",
            "expected": example,
            "got": None,
            "item_match": None,
            "calorie_score": None,
            "matched_item_records": [],
        }
    except Exception as e:  # noqa: BLE001 - deliberately broad, per-example isolation
        elapsed = time.perf_counter() - t0
        log.warning("[run_example] FAILED after %.2fs  input=%r  error=%s", elapsed, meal_text, e)
        return {
            "input": meal_text,
            "format_valid": False,
            "elapsed_s": elapsed,
            "reason": "format_invalid_or_error",
            "error": str(e),
            "expected": example,
            "got": None,
            "item_match": None,
            "calorie_score": None,
            "matched_item_records": [],
        }
    finally:
        # wait=False: don't block here if the call already timed out above —
        # the thread (if still running) is abandoned, not force-killed.
        executor.shutdown(wait=False)

    got_items = result.get("items", [])
    expected_items = example.get("expected_items", [])

    match = match_items(expected_items, got_items)
    calorie_score = score_calories(expected_items, got_items)

    # Build flat matched-item records (confidence + in_range) for calibration scoring.
    matched_item_records = []
    for (exp_idx, got_idx), item_result in zip(match["pairs"], calorie_score["per_item"]):
        got_item = got_items[got_idx]
        matched_item_records.append({
            "confidence": got_item.get("confidence"),
            "in_range": item_result["in_range"],
        })

    return {
        "input": meal_text,
        "format_valid": True,
        "elapsed_s": elapsed,
        "reason": None,
        "error": None,
        "expected": example,
        "got": result,
        "item_match": match,
        "calorie_score": calorie_score,
        "matched_item_records": matched_item_records,
    }


def run_example_via_orchestrator(example: dict[str, Any], timeout_s: float = PER_CALL_TIMEOUT_S) -> dict[str, Any]:
    """ADR-005 Known Limitations #2 (eval-parity gap): run one golden example
    through the REAL production entry point
    (`agent_service._run_agent_orchestrator`), not `parse_meal_text`
    directly, and score the resulting meal dict the same way run_example()
    does.

    Why this exists: before the ADR-005 fix, `_run_agent_orchestrator`
    passed `extract_request_fields`'s LLM-reworded `meal_text` (not the
    user's original wording) into `parse_meal` — so a "parity" score
    obtained by calling `parse_meal_text` directly (as run_example() does)
    proved only that `parse_meal_text` itself hadn't regressed, not that
    end-to-end production behavior matched what this harness measures.
    After the fix, `_run_agent_orchestrator` passes the raw `message`
    straight through to `parse_meal` — the same text run_example() feeds
    parse_meal_text directly. This function is the permanent check that the
    two paths actually agree, by calling the real orchestrator function
    itself rather than reimplementing its call sequence.

    Mechanism: `_run_agent_orchestrator` only returns a human-readable
    string (`AgentResponse.response`), not the structured meal dict this
    harness needs to score. To recover the structured dict without
    reimplementing orchestrator logic, this monkeypatches
    `agent_service.compose_response` (the orchestrator's last internal
    step) to capture its `meal` argument before delegating to the real
    implementation — every LLM call and every decision point up to and
    including which text gets passed to `parse_meal` (extract_request_fields
    classification, the presence-based meal_text routing check, the
    raw-message pass-through itself) is the real, unmodified orchestrator
    code path; only the final formatting step is intercepted, not replaced.

    Runs one example at a time (see run_orchestrator_parity_check), so the
    monkeypatch is not exercised concurrently in the common case. If a call
    times out, the abandoned background thread (see PER_CALL_TIMEOUT_S
    module docstring) could in theory still be mid-flight when the next
    example starts and restore the real compose_response late — the same
    accepted race already documented on run_example()'s timeout path,
    doubled up here since this wraps two LLM calls instead of one.
    """
    message = example["input"]
    captured: dict[str, Any] = {}
    real_compose_response = agent_service.compose_response

    def _capturing_compose_response(calc, meal):
        captured["meal"] = meal
        captured["calc"] = calc
        return real_compose_response(calc, meal)

    def _call():
        agent_service.compose_response = _capturing_compose_response
        try:
            agent_service._run_agent_orchestrator(message, llm=object())
        finally:
            agent_service.compose_response = real_compose_response
        return captured.get("meal")

    t0 = time.perf_counter()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(_call)
    try:
        meal = future.result(timeout=timeout_s)
        elapsed = time.perf_counter() - t0
        log.info("[run_example_via_orchestrator] %.2fs  input=%r", elapsed, message)
    except concurrent.futures.TimeoutError:
        elapsed = time.perf_counter() - t0
        agent_service.compose_response = real_compose_response  # best-effort restore
        log.error(
            "[run_example_via_orchestrator] TIMEOUT after %.1fs (limit %.0fs)  input=%r",
            elapsed, timeout_s, message,
        )
        return {
            "input": message, "format_valid": False, "elapsed_s": elapsed,
            "reason": "timeout", "error": f"orchestrator exceeded {timeout_s:.0f}s timeout",
            "expected": example, "got": None, "item_match": None, "calorie_score": None,
        }
    except Exception as e:  # noqa: BLE001 - deliberately broad, per-example isolation
        elapsed = time.perf_counter() - t0
        agent_service.compose_response = real_compose_response  # best-effort restore
        log.warning("[run_example_via_orchestrator] FAILED after %.2fs  input=%r  error=%s", elapsed, message, e)
        return {
            "input": message, "format_valid": False, "elapsed_s": elapsed,
            "reason": "format_invalid_or_error", "error": str(e),
            "expected": example, "got": None, "item_match": None, "calorie_score": None,
        }
    finally:
        executor.shutdown(wait=False)

    if meal is None:
        # extract_request_fields did not populate meal_text for this
        # message at all -- a real (if rare) divergence: the orchestrator's
        # own presence-based routing decided there was nothing to parse.
        # Recorded as its own failure reason, not folded into
        # "format_invalid_or_error".
        return {
            "input": message, "format_valid": False, "elapsed_s": elapsed,
            "reason": "meal_not_detected_by_extraction",
            "error": "extract_request_fields did not populate meal_text for this input",
            "expected": example, "got": None, "item_match": None, "calorie_score": None,
        }

    expected_items = example.get("expected_items", [])
    got_items = meal.get("items", [])
    match = match_items(expected_items, got_items)
    calorie_score = score_calories(expected_items, got_items)
    return {
        "input": message, "format_valid": True, "elapsed_s": elapsed, "reason": None, "error": None,
        "expected": example, "got": meal, "item_match": match, "calorie_score": calorie_score,
    }


def run_orchestrator_parity_check(direct_results: list[dict[str, Any]], n: int) -> dict[str, Any]:
    """ADR-005 Action Item 17 / Known Limitations #2. Takes the first `n`
    already-scored, format-valid examples from `direct_results` (the normal
    parse_meal_text-direct run) and re-runs each one through the real
    orchestrator entry point (`run_example_via_orchestrator`), reporting
    both scores side by side per example plus an aggregate summary.

    Reuses `direct_results`' existing scoring rather than re-running
    `parse_meal_text` a second time — cheaper, and the direct-path number
    reused here is the exact one already contributing to the committed
    `report/latest.json` baseline, so the two columns are a fair
    apples-to-apples comparison on identical inputs.
    """
    candidates = [r for r in direct_results if r["format_valid"]][:n]
    per_example = []
    for r in candidates:
        example = r["expected"]
        orch = run_example_via_orchestrator(example)

        def _precision(res):
            if not res["format_valid"] or not res["item_match"] or not res["item_match"]["n_got"]:
                return None
            return round(100.0 * res["item_match"]["true_positives"] / res["item_match"]["n_got"], 1)

        def _recall(res):
            if not res["format_valid"] or not res["item_match"] or not res["item_match"]["n_expected"]:
                return None
            return round(100.0 * res["item_match"]["true_positives"] / res["item_match"]["n_expected"], 1)

        per_example.append({
            "input": example["input"],
            "direct_precision_pct": _precision(r),
            "direct_recall_pct": _recall(r),
            "orchestrator_format_valid": orch["format_valid"],
            "orchestrator_reason": orch["reason"],
            "orchestrator_precision_pct": _precision(orch),
            "orchestrator_recall_pct": _recall(orch),
        })

    n_valid = sum(1 for e in per_example if e["orchestrator_format_valid"])
    return {
        "n_examples_checked": len(per_example),
        "n_orchestrator_format_valid": n_valid,
        "per_example": per_example,
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    n_examples = len(results)
    n_format_valid = sum(1 for r in results if r["format_valid"])
    format_valid_pct = round(100.0 * n_format_valid / n_examples, 1) if n_examples else 0.0

    # Format-invalid examples contribute nothing to item/calorie/calibration
    # scoring below — there's no "got" to compare against expected.
    valid_results = [r for r in results if r["format_valid"]]

    # Pooled precision/recall across every matched item in the whole run
    # (not the mean of each example's own precision/recall) — this weights
    # every item equally regardless of which example it came from, so a
    # 6-item example doesn't get the same influence as a 1-item example.
    total_tp = sum(r["item_match"]["true_positives"] for r in valid_results)
    total_got = sum(r["item_match"]["n_got"] for r in valid_results)
    total_expected = sum(r["item_match"]["n_expected"] for r in valid_results)
    item_precision_pct = round(100.0 * total_tp / total_got, 1) if total_got else 0.0
    item_recall_pct = round(100.0 * total_tp / total_expected, 1) if total_expected else 0.0

    # Mean absolute percentage error over every matched item across the
    # whole run (each item's pct_error is already 0-100 scale — see
    # scorers/calorie_accuracy.py). `None` if nothing matched at all.
    all_pct_errors = []
    for r in valid_results:
        for item in r["calorie_score"]["per_item"]:
            if item["pct_error"] is not None:
                all_pct_errors.append(item["pct_error"])
    calorie_mape_pct = round(sum(all_pct_errors) / len(all_pct_errors), 1) if all_pct_errors else None

    all_matched_item_records = [rec for r in valid_results for rec in r["matched_item_records"]]
    calibration = score_confidence_calibration(all_matched_item_records)

    failures = []
    for r in results:
        if not r["format_valid"]:
            failures.append({
                "input": r["input"],
                "reason": r["reason"],
                "expected": r["expected"],
                "got": None,
                "error": r["error"],
            })
        else:
            unmatched_expected = r["item_match"]["unmatched_expected"]
            out_of_range = [item for item in r["calorie_score"]["per_item"] if not item["in_range"]]
            if unmatched_expected or out_of_range:
                failures.append({
                    "input": r["input"],
                    "reason": "missed_items" if unmatched_expected else "calorie_out_of_range",
                    "expected": r["expected"],
                    "got": r["got"],
                    "unmatched_expected": unmatched_expected,
                    "unmatched_got": r["item_match"]["unmatched_got"],
                    "out_of_range_items": out_of_range,
                })

    return {
        "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": MODEL_NAME,
        "n_examples": n_examples,
        "format_valid_pct": format_valid_pct,
        "item_precision_pct": item_precision_pct,
        "item_recall_pct": item_recall_pct,
        "calorie_mape_pct": calorie_mape_pct,
        "confidence_calibration_score_pct": calibration["calibration_score"],
        "confidence_calibration_detail": calibration,
        "failures": failures,
    }


def resolve_dataset_paths(dataset_arg: Path) -> list[Path]:
    if dataset_arg.is_dir():
        paths = sorted(dataset_arg.glob("*.jsonl"))
        if not paths:
            raise SystemExit(f"No .jsonl dataset files found in {dataset_arg}")
        return paths
    return [dataset_arg]


def run_dataset(dataset_path: Path) -> tuple[list[dict[str, Any]], float]:
    """Run every example in one dataset file. Returns (per-example results, elapsed_s)."""
    examples = load_dataset(dataset_path)
    log.info("=== Dataset: %s (%d examples) ===", dataset_path.name, len(examples))
    t0 = time.perf_counter()
    results = []
    for i, example in enumerate(examples, start=1):
        log.info("[%s %d/%d] %r", dataset_path.stem, i, len(examples), example["input"])
        results.append(run_example(example))
    elapsed = time.perf_counter() - t0
    return results, elapsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CalAI meal-parsing eval harness.")
    parser.add_argument(
        "--dataset",
        default=str(EVALS_DIR / "dataset"),
        help="A single .jsonl file, or a directory of them (default: dataset/, runs all).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Path for the combined report (default: report/latest.json). "
             "In directory mode, each dataset also gets its own report/<stem>.json.",
    )
    parser.add_argument(
        "--orchestrator-subset",
        type=int,
        default=0,
        help="ADR-005 Known Limitations #2: also re-run the first N already-scored, "
             "format-valid examples through the real orchestrator entry point "
             "(_run_agent_orchestrator) and write report/orchestrator_parity.json "
             "comparing direct-path vs orchestrator-path scores. Default 0 = skipped "
             "(does not affect the default run or report/latest.json).",
    )
    parser.add_argument(
        "--orchestrator-report",
        default=None,
        help="Path for the orchestrator-parity report (default: report/orchestrator_parity.json). "
             "Only used when --orchestrator-subset > 0.",
    )
    args = parser.parse_args()

    dataset_arg = Path(args.dataset)
    dataset_paths = resolve_dataset_paths(dataset_arg)
    combined_out = Path(args.out) if args.out else (EVALS_DIR / "report" / "latest.json")

    log.info("Model under test: %s", MODEL_NAME)
    log.info("Datasets: %s", [p.name for p in dataset_paths])

    all_results: list[dict[str, Any]] = []
    per_dataset_summary: dict[str, Any] = {}
    t_all_start = time.perf_counter()

    for dataset_path in dataset_paths:
        results, elapsed = run_dataset(dataset_path)
        # Step 6 (per dataset): score+pool this one dataset's examples.
        report = aggregate(results)
        report["total_wall_clock_s"] = round(elapsed, 1)
        report["dataset"] = dataset_path.name

        # Per-dataset report is only written when scoring multiple datasets
        # (directory mode) — single-file mode writes only the combined report
        # at --out, preserving the original single-dataset behavior.
        if dataset_arg.is_dir():
            per_report_path = EVALS_DIR / "report" / f"{dataset_path.stem}.json"
            per_report_path.parent.mkdir(parents=True, exist_ok=True)
            with open(per_report_path, "w") as f:
                json.dump(report, f, indent=2)
            log.info("Wrote %s report to %s", dataset_path.stem, per_report_path)

        per_dataset_summary[dataset_path.stem] = {
            "n_examples": report["n_examples"],
            "format_valid_pct": report["format_valid_pct"],
            "item_precision_pct": report["item_precision_pct"],
            "item_recall_pct": report["item_recall_pct"],
            "calorie_mape_pct": report["calorie_mape_pct"],
            "confidence_calibration_score_pct": report["confidence_calibration_score_pct"],
            "wall_clock_s": report["total_wall_clock_s"],
        }
        # Step 7: also keep every raw per-example result so the combined
        # (all-datasets) report below is pooled from real per-item data,
        # not an average-of-averages of the per-dataset numbers.
        all_results.extend(results)

    total_elapsed_all = time.perf_counter() - t_all_start

    combined_report = aggregate(all_results)
    combined_report["total_wall_clock_s"] = round(total_elapsed_all, 1)
    combined_report["datasets"] = [p.name for p in dataset_paths]
    combined_report["per_dataset_summary"] = per_dataset_summary

    combined_out.parent.mkdir(parents=True, exist_ok=True)
    with open(combined_out, "w") as f:
        json.dump(combined_report, f, indent=2)

    log.info("Wrote combined report to %s", combined_out)
    log.info(
        "COMBINED format_valid=%.1f%%  precision=%.1f%%  recall=%.1f%%  mape=%s  calibration=%s  wall_clock=%.1fs",
        combined_report["format_valid_pct"], combined_report["item_precision_pct"], combined_report["item_recall_pct"],
        combined_report["calorie_mape_pct"], combined_report["confidence_calibration_score_pct"], total_elapsed_all,
    )

    if args.orchestrator_subset > 0:
        log.info(
            "Running orchestrator-parity check on first %d format-valid examples "
            "(ADR-005 Known Limitations #2)...", args.orchestrator_subset,
        )
        parity_report = run_orchestrator_parity_check(all_results, args.orchestrator_subset)
        orchestrator_out = (
            Path(args.orchestrator_report) if args.orchestrator_report
            else (EVALS_DIR / "report" / "orchestrator_parity.json")
        )
        orchestrator_out.parent.mkdir(parents=True, exist_ok=True)
        with open(orchestrator_out, "w") as f:
            json.dump(parity_report, f, indent=2)
        log.info(
            "Wrote orchestrator-parity report to %s  (%d/%d format-valid through orchestrator)",
            orchestrator_out, parity_report["n_orchestrator_format_valid"], parity_report["n_examples_checked"],
        )


if __name__ == "__main__":
    main()
