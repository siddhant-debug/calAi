"""Tests for evals/run_eval.py's ADR-006 additions: per-model scoring
(`--model` / `override_models`) and the baseline pass/fail gate
(`--gate` / `--baseline` / `--tolerance-pct` / `compare_to_baseline`).

No real network calls or `parse_meal_text` invocations here — every CLI-level
test monkeypatches `evals.run_eval.parse_meal_text` (the name run_eval.py
itself binds via `from calai_backend.tools.meal_parser import
parse_meal_text`) to a deterministic fake, following this repo's
FakeLLM/monkeypatch convention (see test_providers_llm.py,
test_meal_parse_agent.py). `compare_to_baseline` is pure and needs no
mocking at all.

Covers:
1. `override_models` monkeypatches all three LLM_MODELS bindings
   (calai_backend.config, calai_backend.providers.llm, evals.run_eval's own
   module-global) and restores the exact original list objects afterward,
   including when the `with` block raises.
2. `--model` output-path sanitization (`report/<model>.json`, `--out` wins,
   empty/whitespace `--model` raises SystemExit before touching dataset/out
   plumbing).
3. `compare_to_baseline`'s pure regression logic: calorie_mape_pct
   (lower-is-better) vs every other `_pct` field (higher-is-better), missing
   baseline file, unreadable baseline, missing field on either side, deltas
   within vs beyond tolerance.
4. `--gate` exit-code contract at the CLI level (omitted, passed+clean,
   passed+regression, passed+missing baseline).
"""
from __future__ import annotations

import json
import sys

import pytest

from calai_backend import config as calai_config
from calai_backend.providers import llm as llm_provider
from evals import run_eval


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------

def _fake_parse_meal_text_factory(kcal: float, confidence: str = "high"):
    """Returns a fake parse_meal_text(meal_text, meal_type) that always
    reports one item named to fuzzy-match "banana" at a fixed kcal value."""

    def _fake(meal_text, meal_type):
        return {
            "items": [
                {
                    "name": "banana",
                    "quantity": 1,
                    "unit": "piece",
                    "calories_kcal": kcal,
                    "confidence": confidence,
                }
            ],
            "meal_type": meal_type,
        }

    return _fake


@pytest.fixture
def one_example_dataset(tmp_path, monkeypatch):
    """A single-example dataset dir whose golden range is [90, 110]
    (midpoint 100) so a fake parse_meal_text returning exactly 100 kcal
    scores a clean 100% precision/recall/format_valid and 0.0 MAPE.

    Also redirects run_eval.EVALS_DIR to tmp_path: dataset-directory mode
    (which this fixture always is) makes main() write a per-dataset report
    to EVALS_DIR/report/<stem>.json unconditionally, regardless of --out --
    without this redirect that write would land in the real repo's
    evals/report/ directory as a side effect of running this test suite.
    """
    monkeypatch.setattr(run_eval, "EVALS_DIR", tmp_path)
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    example = {
        "input": "a banana",
        "meal_type": "snack",
        "expected_items": [
            {"name": "banana", "quantity": 1, "unit": "piece", "calories_kcal_range": [90, 110]}
        ],
        "expected_total_kcal_range": [90, 110],
    }
    (dataset_dir / "fruit.jsonl").write_text(json.dumps(example) + "\n")
    return dataset_dir


def _run_main(monkeypatch, argv):
    monkeypatch.setattr(sys, "argv", ["run_eval.py", *argv])
    run_eval.main()


# ---------------------------------------------------------------------------
# 1. override_models monkeypatch/restore mechanics
# ---------------------------------------------------------------------------

def test_override_models_patches_all_three_bindings():
    original_config = calai_config.LLM_MODELS
    original_provider = llm_provider.LLM_MODELS
    original_run_eval = run_eval.LLM_MODELS

    with run_eval.override_models("fake/model-x") as override:
        assert override == ["fake/model-x"]
        assert calai_config.LLM_MODELS == ["fake/model-x"]
        assert llm_provider.LLM_MODELS == ["fake/model-x"]
        assert run_eval.LLM_MODELS == ["fake/model-x"]

    # Restored to the exact original list objects, not just equal-valued copies.
    assert calai_config.LLM_MODELS is original_config
    assert llm_provider.LLM_MODELS is original_provider
    assert run_eval.LLM_MODELS is original_run_eval


def test_override_models_restores_after_exception_inside_block():
    original_config = calai_config.LLM_MODELS
    original_provider = llm_provider.LLM_MODELS
    original_run_eval = run_eval.LLM_MODELS

    with pytest.raises(RuntimeError, match="boom"):
        with run_eval.override_models("fake/model-y"):
            assert calai_config.LLM_MODELS == ["fake/model-y"]
            raise RuntimeError("boom")

    # finally: still restores every binding even though the block raised.
    assert calai_config.LLM_MODELS is original_config
    assert llm_provider.LLM_MODELS is original_provider
    assert run_eval.LLM_MODELS is original_run_eval


# ---------------------------------------------------------------------------
# 2. --model output-path sanitization / empty-model guard
# ---------------------------------------------------------------------------

def test_model_flag_defaults_output_to_sanitized_report_path(monkeypatch, one_example_dataset, tmp_path):
    # one_example_dataset already redirects run_eval.EVALS_DIR to tmp_path.
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(100.0))

    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--model", "meta/llama-3.1-8b-instruct",
    ])

    expected_path = tmp_path / "report" / "meta_llama-3.1-8b-instruct.json"
    assert expected_path.exists()
    report = json.loads(expected_path.read_text())
    # aggregate()'s "model" field reflects the single overridden model, not
    # the full ADR-006 fallback chain.
    assert report["model"] == ["meta/llama-3.1-8b-instruct"]


def test_out_flag_wins_over_model_default_path(monkeypatch, one_example_dataset, tmp_path):
    # one_example_dataset already redirects run_eval.EVALS_DIR to tmp_path.
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(100.0))
    explicit_out = tmp_path / "custom" / "wherever.json"

    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--model", "meta/llama-3.1-8b-instruct",
        "--out", str(explicit_out),
    ])

    assert explicit_out.exists()
    default_path = tmp_path / "report" / "meta_llama-3.1-8b-instruct.json"
    assert not default_path.exists()


def test_model_flag_sanitizes_slashes_and_colons(monkeypatch, one_example_dataset, tmp_path):
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(100.0))

    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--model", "qwen2.5:3b",
        "--out", str(tmp_path / "colon_test.json"),
    ])
    # No slashes/colons should leak into a filesystem path anywhere the
    # sanitized name is used — verified indirectly via the report content.
    report = json.loads((tmp_path / "colon_test.json").read_text())
    assert report["model"] == ["qwen2.5:3b"]


@pytest.mark.parametrize("bad_model", ["", "   "])
def test_empty_or_whitespace_model_raises_systemexit_before_touching_dataset(monkeypatch, bad_model):
    def _explode(*args, **kwargs):
        raise AssertionError("resolve_dataset_paths should not be called for an empty --model")

    monkeypatch.setattr(run_eval, "resolve_dataset_paths", _explode)

    with pytest.raises(SystemExit):
        _run_main(monkeypatch, ["--model", bad_model])


# ---------------------------------------------------------------------------
# 3. compare_to_baseline pure logic
# ---------------------------------------------------------------------------

def test_compare_to_baseline_missing_file_is_graceful(tmp_path):
    passed, messages = run_eval.compare_to_baseline(
        {"format_valid_pct": 100.0}, tmp_path / "does_not_exist.json", tolerance_pct=5.0
    )
    assert passed is True
    assert len(messages) == 1
    assert "No baseline found" in messages[0]


def test_compare_to_baseline_unreadable_file_is_graceful(tmp_path):
    bad_baseline = tmp_path / "corrupt.json"
    bad_baseline.write_text("{not valid json")

    passed, messages = run_eval.compare_to_baseline(
        {"format_valid_pct": 100.0}, bad_baseline, tolerance_pct=5.0
    )
    assert passed is True
    assert len(messages) == 1


def test_compare_to_baseline_missing_field_is_skipped(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"item_precision_pct": 80.0}))

    # new_report has a field the baseline lacks, and lacks a field the
    # baseline has -- neither should raise or count as a regression.
    passed, messages = run_eval.compare_to_baseline(
        {"format_valid_pct": 100.0}, baseline, tolerance_pct=5.0
    )
    assert passed is True
    assert messages == []


def test_compare_to_baseline_within_tolerance_passes(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"item_precision_pct": 80.0, "calorie_mape_pct": 20.0}))

    passed, messages = run_eval.compare_to_baseline(
        {"item_precision_pct": 76.0, "calorie_mape_pct": 24.0},  # both 4pp deltas
        baseline,
        tolerance_pct=5.0,
    )
    assert passed is True
    assert messages == []


def test_compare_to_baseline_higher_is_better_field_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"item_precision_pct": 83.6}))

    # A drop of more than tolerance is a regression for a higher-is-better field.
    passed, messages = run_eval.compare_to_baseline(
        {"item_precision_pct": 70.0}, baseline, tolerance_pct=5.0
    )
    assert passed is False
    assert len(messages) == 1
    assert "item_precision_pct" in messages[0]


def test_compare_to_baseline_higher_is_better_field_improvement_is_not_a_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"item_recall_pct": 80.0}))

    # An increase is always fine for a higher-is-better field, regardless of size.
    passed, messages = run_eval.compare_to_baseline(
        {"item_recall_pct": 99.0}, baseline, tolerance_pct=5.0
    )
    assert passed is True
    assert messages == []


def test_compare_to_baseline_calorie_mape_regression_is_an_increase(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"calorie_mape_pct": 59.3}))

    # calorie_mape_pct is lower-is-better: an increase beyond tolerance is
    # the regression direction, not a decrease.
    passed, messages = run_eval.compare_to_baseline(
        {"calorie_mape_pct": 70.0}, baseline, tolerance_pct=5.0
    )
    assert passed is False
    assert "calorie_mape_pct" in messages[0]


def test_compare_to_baseline_calorie_mape_decrease_is_not_a_regression(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"calorie_mape_pct": 59.3}))

    # A decrease in MAPE (error went down) is an improvement, never flagged.
    passed, messages = run_eval.compare_to_baseline(
        {"calorie_mape_pct": 10.0}, baseline, tolerance_pct=5.0
    )
    assert passed is True
    assert messages == []


def test_compare_to_baseline_none_values_are_skipped(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"calorie_mape_pct": None, "confidence_calibration_score_pct": 39.6}))

    passed, messages = run_eval.compare_to_baseline(
        {"calorie_mape_pct": 90.0, "confidence_calibration_score_pct": None},
        baseline,
        tolerance_pct=5.0,
    )
    assert passed is True
    assert messages == []


def test_compare_to_baseline_ignores_non_pct_fields(tmp_path):
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"n_examples": 33, "model": ["qwen2.5:3b"]}))

    passed, messages = run_eval.compare_to_baseline(
        {"n_examples": 1, "model": ["different-model"]}, baseline, tolerance_pct=5.0
    )
    assert passed is True
    assert messages == []


# ---------------------------------------------------------------------------
# 4. --gate exit-code contract at the CLI level
# ---------------------------------------------------------------------------

def test_gate_omitted_exits_zero_even_with_bad_scores(monkeypatch, one_example_dataset, tmp_path):
    # 300 kcal is wildly outside the golden [90, 110] range -- a very bad
    # score -- but without --gate the run must still exit 0.
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(300.0))

    # main() returning normally (no SystemExit) is the exit-0 behavior we're
    # asserting; if --gate accidentally fired here this call would raise.
    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--out", str(tmp_path / "out.json"),
    ])


def test_gate_passed_no_regression_exits_zero(monkeypatch, one_example_dataset, tmp_path):
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(100.0))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({
        "format_valid_pct": 100.0,
        "item_precision_pct": 100.0,
        "item_recall_pct": 100.0,
        "calorie_mape_pct": 5.0,  # our fake scores 0.0 -- an improvement, not a regression
    }))

    # No SystemExit raised == exit code 0.
    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--out", str(tmp_path / "out.json"),
        "--gate",
        "--baseline", str(baseline),
        "--tolerance-pct", "5.0",
    ])


def test_gate_passed_with_regression_exits_one(monkeypatch, one_example_dataset, tmp_path):
    # 300 kcal vs golden midpoint 100 is a huge pct_error, driving
    # calorie_mape_pct far above a baseline of 5.0 -- a clear regression.
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(300.0))
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"calorie_mape_pct": 5.0}))

    with pytest.raises(SystemExit) as exc_info:
        _run_main(monkeypatch, [
            "--dataset", str(one_example_dataset),
            "--out", str(tmp_path / "out.json"),
            "--gate",
            "--baseline", str(baseline),
            "--tolerance-pct", "5.0",
        ])
    assert exc_info.value.code == 1


def test_compare_to_baseline_delta_equal_tolerance_is_not_a_regression(tmp_path):
    # Boundary case: delta == tolerance_pct exactly. compare_to_baseline's
    # check is a strict `delta > tolerance_pct`, so a delta that exactly
    # equals the tolerance passes (not >=). This test pins down that
    # observed behavior; it does not assert it's the "right" choice.
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"item_precision_pct": 80.0}))

    passed, messages = run_eval.compare_to_baseline(
        {"item_precision_pct": 75.0},  # delta = old - new = 5.0, exactly == tolerance
        baseline,
        tolerance_pct=5.0,
    )
    assert passed is True
    assert messages == []


# ---------------------------------------------------------------------------
# 5. --model + --orchestrator-subset: overridden model must stay in effect
#    for the ENTIRE `with models_cm:` block, including the orchestrator-
#    parity path, not just the main dataset run (reviewer-found bug, fixed
#    by widening the `with` scope in main()).
# ---------------------------------------------------------------------------

def test_model_override_still_in_effect_during_orchestrator_subset(monkeypatch, one_example_dataset, tmp_path):
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(100.0))

    seen_models_during_orchestrator_call: list[list[str]] = []

    def _fake_run_example_via_orchestrator(example, timeout_s=None):
        # Record the LLM_MODELS binding *at the moment this is called* --
        # this is exactly the value that would leak the bug if the `with
        # models_cm:` block had already exited (restoring the original
        # 4-model chain) before this ran.
        seen_models_during_orchestrator_call.append(list(run_eval.LLM_MODELS))
        return {
            "input": example["input"], "format_valid": True, "elapsed_s": 0.0,
            "reason": None, "error": None, "expected": example,
            "got": {"items": [], "meal_type": example.get("meal_type")},
            "item_match": {"true_positives": 0, "n_got": 0, "n_expected": 0},
            "calorie_score": None,
        }

    monkeypatch.setattr(
        run_eval, "run_example_via_orchestrator", _fake_run_example_via_orchestrator
    )

    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--out", str(tmp_path / "out.json"),
        "--model", "fake/override-model",
        "--orchestrator-subset", "1",
    ])

    # The orchestrator-parity path must have run at all (otherwise this test
    # would pass vacuously) and must have seen the single overridden model,
    # not the restored full ADR-006 fallback chain.
    assert seen_models_during_orchestrator_call == [["fake/override-model"]]
    # And the binding is restored to normal after main() returns.
    assert run_eval.LLM_MODELS != ["fake/override-model"]
    assert len(run_eval.LLM_MODELS) > 1


def test_gate_passed_missing_baseline_exits_zero(monkeypatch, one_example_dataset, tmp_path):
    monkeypatch.setattr(run_eval, "parse_meal_text", _fake_parse_meal_text_factory(100.0))

    # No SystemExit raised == exit code 0, even though --gate was passed --
    # a missing baseline is skipped gracefully, never a failure by itself.
    _run_main(monkeypatch, [
        "--dataset", str(one_example_dataset),
        "--out", str(tmp_path / "out.json"),
        "--gate",
        "--baseline", str(tmp_path / "no_such_baseline.json"),
    ])
