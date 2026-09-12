"""ADR-003 Action Item 7 / Migration Plan step 5: latency comparison between
the old ReAct loop (`_run_agent_react_loop`) and the new Orchestrator
(`_run_agent_orchestrator`) in `calai_backend/services/agent_service.py`.

This is a standalone measurement artifact, NOT a pytest test — it makes real
Ollama calls, is slow, and has no pass/fail assertion. It is not picked up
by pytest (no `test_` prefix, lives outside `calai_backend/tests/`) and is
not part of `evals/run_eval.py`'s meal-parsing-quality harness (ADR-004's
Non-Goals section explicitly excludes latency from that scoring — this file
is the separate artifact that covers it, alongside the per-call timing
already logged by both paths via `time.perf_counter()`).

What this does, in order:
1. Defines a small, fixed set of representative messages covering the
   shapes `/api/agent` receives: profile-only, meal-only, and combined
   profile+meal (see MESSAGES below).
2. For each message, runs it through BOTH `_run_agent_react_loop` and
   `_run_agent_orchestrator`, timing each call with `time.perf_counter()`.
   Both paths take the same `(message, llm)` signature; `llm` is a single
   real `get_llm()` instance shared across all calls (matches how
   `run_agent` is actually invoked from `routes.py` — one LLM instance per
   process, not per request). Note: the orchestrator's own internal calls
   (`extract_request_fields`, `parse_meal`) ignore the passed `llm` and
   construct their own `get_json_llm()` internally — see agent_service.py's
   docstring on `extract_request_fields` — but the parameter still has to
   be passed here to match the function signature.
3. Records per message/path: path name, wall-clock seconds,
   `iterations_used` from the returned `AgentResponse`, and the final
   `response` text (for eyeballing quality alongside speed).
4. Runs each message through each path exactly ONCE. This is real-LLM
   timing against a live Ollama instance, not a statistical study written
   for many repeated runs — one clean run per message/path is the right
   scope for this artifact. Repeated runs (e.g. median of 3) would reduce
   noise but are not required here; if the numbers this produces are noisy
   or surprising, re-run the whole script rather than adding retry/averaging
   logic to it.
5. Prints a summary table: message -> react_loop_seconds vs
   orchestrator_seconds vs speedup ratio, plus an overall total across all
   messages for both paths.

Usage (from repo root):
    python evals/latency_comparison.py

ADR-006: requires a real NVIDIA_API_KEY (NVIDIA NIM) set in the
environment. Up to 6 real NIM round-trips total
(3 messages x 2 paths); the ReAct loop path can take up to MAX_STEPS=8
LLM+tool iterations per call if the model doesn't converge quickly, so a
full run can take several minutes. This is expected to be run by `reviewer`
to gather the authoritative numbers for the ADR-003 report, not run
repeatedly during development.

---

ADR-005 addition — `--meal-only-check N` (default off): checks the
`artefacts/NOTES-orchestrator-vs-react.md` retrospective's "per-request
latency, meal path" prediction (**~1.8x better**, 73.2s -> ~41s) against
what ADR-005's actual fix implemented. That prediction explicitly assumed
`extract_request_fields` would be SKIPPED entirely on the meal path (the
1.8x came from dropping one whole LLM call). The fix that actually shipped
(closing Known Limitations item 2, the eval-parity gap) does NOT skip
extraction — it still runs once per request, exactly as before — and only
changes which text string gets passed into the second call (`parse_meal`):
the raw `message` instead of `parsed_request.meal_text`. Both are two LLM
calls of comparable prompt/response size, so the honest expectation is
**flat/neutral latency versus the `meal_only` baseline (73.20s, see
artefacts/adr003-latency-comparison.json)**, not the 1.8x speedup — this
flag exists to measure that honestly rather than assume it. Runs the
`meal_only` message through `_run_agent_orchestrator` N times (see
run_meal_only_repeated()) and reports mean/median wall-clock seconds.

    python evals/latency_comparison.py --meal-only-check 3
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Any

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from calai_backend.config import LLM_MODELS  # noqa: E402
from calai_backend.providers.llm import get_llm  # noqa: E402
from calai_backend.services.agent_service import (  # noqa: E402
    _run_agent_orchestrator,
    _run_agent_react_loop,
)

# Representative message shapes for /api/agent, per ADR-003's migration plan.
MESSAGES: list[tuple[str, str]] = [
    (
        "profile_only",
        "I'm a 28 year old male, 75kg, 178cm tall, moderately active, "
        "and I want to lose weight at 0.5kg per week.",
    ),
    (
        "meal_only",
        "I just had 2 eggs and a slice of toast for breakfast.",
    ),
    (
        "profile_and_meal",
        "I'm a 25 year old female, 60kg, 165cm, lightly active, trying to "
        "maintain. I had a bowl of oatmeal with banana for breakfast.",
    ),
]

PATHS: list[tuple[str, Any]] = [
    ("react_loop", _run_agent_react_loop),
    ("orchestrator", _run_agent_orchestrator),
]


def run_comparison() -> list[dict[str, Any]]:
    """Run every message through both paths once. Returns a flat list of
    per-(message, path) result records. Never averages/retries — see module
    docstring point 4."""
    llm = get_llm()
    records: list[dict[str, Any]] = []

    for label, message in MESSAGES:
        for path_name, path_fn in PATHS:
            print(f"\n--- Running [{label}] via [{path_name}] ---")
            print(f"Message: {message!r}")
            t0 = time.perf_counter()
            try:
                result = path_fn(message, llm)
                elapsed_s = time.perf_counter() - t0
                records.append({
                    "label": label,
                    "message": message,
                    "path": path_name,
                    "elapsed_s": elapsed_s,
                    "iterations_used": result.iterations_used,
                    "response": result.response,
                    "error": None,
                })
                print(f"OK  {elapsed_s:.2f}s  iterations_used={result.iterations_used}")
                print(f"Response: {result.response}")
            except Exception as e:  # noqa: BLE001 - one path's failure shouldn't kill the run
                elapsed_s = time.perf_counter() - t0
                records.append({
                    "label": label,
                    "message": message,
                    "path": path_name,
                    "elapsed_s": elapsed_s,
                    "iterations_used": None,
                    "response": None,
                    "error": str(e),
                })
                print(f"FAILED after {elapsed_s:.2f}s: {e}")

    return records


def print_summary(records: list[dict[str, Any]]) -> None:
    by_label: dict[str, dict[str, dict[str, Any]]] = {}
    for r in records:
        by_label.setdefault(r["label"], {})[r["path"]] = r

    print("\n" + "=" * 78)
    print(f"LATENCY COMPARISON — models={LLM_MODELS}")
    print("=" * 78)
    header = f"{'message':<20} {'react_loop_s':>14} {'orchestrator_s':>16} {'speedup':>10}"
    print(header)
    print("-" * len(header))

    total_react = 0.0
    total_orch = 0.0
    for _, message in MESSAGES:
        label = next(l for l, m in MESSAGES if m == message)
        react = by_label.get(label, {}).get("react_loop")
        orch = by_label.get(label, {}).get("orchestrator")
        react_s = react["elapsed_s"] if react and react["error"] is None else float("nan")
        orch_s = orch["elapsed_s"] if orch and orch["error"] is None else float("nan")
        if react:
            total_react += react["elapsed_s"]
        if orch:
            total_orch += orch["elapsed_s"]
        speedup = (react_s / orch_s) if orch_s and orch_s == orch_s and orch_s > 0 else float("nan")
        print(f"{label:<20} {react_s:>14.2f} {orch_s:>16.2f} {speedup:>9.2f}x")

    print("-" * len(header))
    overall_speedup = (total_react / total_orch) if total_orch > 0 else float("nan")
    print(f"{'TOTAL':<20} {total_react:>14.2f} {total_orch:>16.2f} {overall_speedup:>9.2f}x")
    print("=" * 78)

    any_errors = [r for r in records if r["error"] is not None]
    if any_errors:
        print("\nErrors encountered:")
        for r in any_errors:
            print(f"  [{r['label']}/{r['path']}]: {r['error']}")


MEAL_ONLY_MESSAGE = next(m for label, m in MESSAGES if label == "meal_only")

# Baseline for comparison — ADR-003's real-Ollama measurement of the
# orchestrator path on this exact message, pre-ADR-005
# (artefacts/adr003-latency-comparison.json). The NOTES retrospective's
# "~1.8x better" prediction was ~41s; this is the number that prediction
# was measured against.
MEAL_ONLY_BASELINE_S = 73.20


def run_meal_only_repeated(n: int) -> list[float]:
    """ADR-005 addition: run the meal_only message through
    `_run_agent_orchestrator` N times, real Ollama calls, no mocking.
    Returns the list of per-run wall-clock seconds. See module docstring's
    "ADR-005 addition" section for what this checks and why flat/neutral
    latency (not the ~1.8x prediction) is the honest expectation here."""
    llm = get_llm()
    timings: list[float] = []
    for i in range(1, n + 1):
        print(f"\n--- meal_only run {i}/{n} ---")
        t0 = time.perf_counter()
        result = _run_agent_orchestrator(MEAL_ONLY_MESSAGE, llm)
        elapsed_s = time.perf_counter() - t0
        timings.append(elapsed_s)
        print(f"OK  {elapsed_s:.2f}s  iterations_used={result.iterations_used}")
    return timings


def print_meal_only_summary(timings: list[float]) -> None:
    mean_s = statistics.mean(timings)
    median_s = statistics.median(timings)
    ratio_vs_baseline = MEAL_ONLY_BASELINE_S / mean_s if mean_s else float("nan")
    predicted_1_8x_target_s = MEAL_ONLY_BASELINE_S / 1.8

    print("\n" + "=" * 78)
    print(f"MEAL-ONLY LATENCY CHECK (ADR-005 vs NOTES 1.8x prediction) — models={LLM_MODELS}")
    print("=" * 78)
    print(f"Runs: {[f'{t:.2f}s' for t in timings]}")
    print(f"Mean:   {mean_s:.2f}s")
    print(f"Median: {median_s:.2f}s")
    print(f"ADR-003 pre-ADR-005 baseline (meal_only, orchestrator path): {MEAL_ONLY_BASELINE_S:.2f}s")
    print(f"NOTES.md's ~1.8x-better predicted target (IF extraction were skipped): ~{predicted_1_8x_target_s:.2f}s")
    print(f"Measured ratio vs baseline: {ratio_vs_baseline:.2f}x (1.0x = flat/neutral, as this fix predicts)")
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="ADR-003/ADR-005 latency comparison for agent_service.")
    parser.add_argument(
        "--meal-only-check", type=int, default=0, metavar="N",
        help="Run the meal_only message through the orchestrator N times and report mean/median "
             "latency vs the ~1.8x NOTES.md prediction, instead of the full react-vs-orchestrator "
             "comparison. Default 0 = run the normal full comparison.",
    )
    args = parser.parse_args()

    print(f"Models under test (ADR-006 fallback chain): {LLM_MODELS}")

    if args.meal_only_check > 0:
        print(f"Meal-only repeated check: {args.meal_only_check} runs")
        timings = run_meal_only_repeated(args.meal_only_check)
        print_meal_only_summary(timings)
        return

    print(f"Messages: {[label for label, _ in MESSAGES]}")
    print(f"Paths: {[name for name, _ in PATHS]}")
    records = run_comparison()
    print_summary(records)


if __name__ == "__main__":
    main()
