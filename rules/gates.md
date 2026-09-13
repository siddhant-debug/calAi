# Rule: the exact gate commands

Run these yourself and cite exit codes — never take an engineer's word for them.

| Gate | Command | When |
|---|---|---|
| Backend tests | `python -m pytest calai_backend/tests -v` | Any backend change |
| Frontend analysis | `cd calai_frontend && dart analyze lib` | Any frontend change |
| Frontend tests | `cd calai_frontend && flutter test` | Any frontend change |
| Eval gate | `python evals/run_eval.py --gate --baseline evals/report/latest.json --tolerance-pct 5` | Only when a prompt, model, or meal-parsing/extraction path changed |

Notes:
- There is **no root `tests/`** directory — `pytest tests/ -v` collects zero tests and exits 0.
  Always use the `calai_backend/tests` path above.
- The eval gate's tolerance here is `run_eval.py`'s own default (**5.0**). If a stricter value is
  ever wanted for a specific change, record the reason in the run record, not just in one
  agent's report — otherwise the number silently drifts between callers.
- If a gate can't run in this environment, say so explicitly — an unrun gate is an open finding,
  not a pass.

Referenced by: `reviewer.md`, `CLAUDE.md`.
