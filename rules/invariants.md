# Rule: things that look removable and are not

A generic cleanup pass — `/simplify`, or any plugin skill's own judgment — does not read this
project's ADRs. It optimizes for removing what looks redundant, and "this isn't earning its
keep" is exactly the judgment that requires knowing *why* something exists. These items in this
repo look like dead code or unnecessary complexity and are load-bearing. Check this file before
removing any of them, and add a row whenever another one is found.

| What it looks like | What it actually is | Reference |
|---|---|---|
| Legacy ReAct loop duplicating `Orchestrator` | Kept for rollback — step 8 pending explicit user go-ahead | ADR-003 |
| `LLM_MODELS` as a 2-element list | Required retry+fallback chain; one model is not enough | ADR-006 |
| Flutter tolerating `detail` as string **or** list | **Stale as of the P1 error-envelope fix (2026-09-14)** — the backend now returns one shape everywhere: `{"detail": {"message": <str>, "errors": <list\|null>}}`. Existing Flutter code written against the old two-shape contract needs updating to read `detail.message`/`detail.errors`, not kept as a tolerance shim — this row should be deleted once that update lands | `rules/backend-facts.md` |
| Tool-name sanitization in `agent_service.py`'s dispatch loop | Fix for the Harmony-format tool-name corruption bug, with 3 regression tests behind it | `CLAUDE.md` §Architecture docs & eval baseline |

Referenced by: `CLAUDE.md`, `reviewer.md` (bucket-2 guardrail: check this list before
recommending removal of anything on it).
