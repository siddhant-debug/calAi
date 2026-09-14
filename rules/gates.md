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

## Restart long-running processes before any manual re-test

A `uvicorn` server started earlier in a session keeps serving the code it loaded at startup.
`pytest` passing proves the *files* are correct; it says nothing about what a running process is
serving. After any `calai_backend/` change, restart the server before re-testing by hand, and
rebuild + relaunch the app after any `calai_frontend/` change.

Why this is a rule: on 2026-09-14 the ADR-008 fix passed both halves of review (144/144 pytest,
26/26 flutter test) and the live re-test *still* reproduced the original bug — because the local
server had been running since before the fix landed. Ten minutes went into re-reading correct
code looking for a defect that wasn't there.

## What the gates structurally cannot catch

Passing gates are necessary, not sufficient. These three classes are invisible to them, so a
user-facing unit needs a real end-to-end run before it's called done:

1. **Config at a faked boundary.** Tests inject `FakeApiService`, so the real `baseUrl` is never
   exercised. `api_service.dart` shipped with a literal unfilled `http://<LOCAL_IP>:8000/api`
   placeholder through a full green suite and a reviewer pass — the app could never have reached
   the backend, and nothing failed.
2. **Behaviour that spans calls.** A single-request test can't see state that must carry between
   requests — see ADR-008's onboarding slot-filling, correct per-call and broken across turns.
3. **Cache/lifecycle staleness.** A provider that reads correctly on first build can serve stale
   data forever after; a test that reads once always sees a fresh build. The `historyProvider`
   bug needed a cache-then-mutate-then-read sequence to reproduce.

Both real bugs found on 2026-09-14 were found by *using the app*, not by the suite or review.

Referenced by: `reviewer.md`, `CLAUDE.md`.
