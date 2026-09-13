# 06 — Learning roadmap: what to learn in parallel, tied to this repo

Ordered by *what unlocks the next step of the action plan*, not by difficulty. Each item:
what to learn → why it matters here → the concrete task in this repo that proves you learned
it. Aim for 2 tracks at a time (one "mechanics", one "AI").

## Track A — Engineering mechanics (the boring half that makes it production)

| # | Learn | Why here | Prove it by |
|---|---|---|---|
| A1 | `pyproject.toml`, `ruff`, `pre-commit`, pinned deps | G1/G2: rules become mechanisms | Step 0 of the action plan |
| A2 | GitHub Actions: jobs, path filters, secrets, caching | G1 | CI green on a PR; evals job skipped unless prompts change |
| A3 | `pytest` deeply: fixtures, `parametrize`, `monkeypatch`, `tmp_path`, `--cov`, markers | 05 §1–3 | route table test for `route_fn`; matrix rows P1–P13 |
| A4 | FastAPI production: exception handlers, middleware (CORS, request-id), `pydantic-settings`, lifespan, SSE (`StreamingResponse`), OpenAPI export | G11, blockers 1/1b/1c, 04 §6 | Step 4 + Release checklist |
| A5 | Docker basics (multi-stage, non-root, env), `docker compose` | Release | `docker compose up` runs backend + serves Flutter web |
| A6 | Structured logging + correlation ids; reading JSONL logs with `jq` | ADR-005 logging contract | one `jq` query that shows every `needs_more_info` last week |
| A7 | Git hygiene for solo shipping: branches per unit, conventional commits, tags, `CHANGELOG` | Release | first tagged release `v0.1.0` |

## Track B — AI engineering (LangChain / LangGraph / evals)

| # | Learn | Why here | Prove it by |
|---|---|---|---|
| B1 | LangChain core: Runnables/LCEL, `with_structured_output`, tools, `with_retry`, `with_fallbacks`, callbacks | your `providers/llm.py` already uses half of this; understand the rest | rewrite `extract` with `with_structured_output(ParsedRequest)` + validation-feedback retry |
| B2 | LangGraph: `StateGraph`, reducers, conditional edges, `Command`, `interrupt`, checkpointers, subgraphs, `recursion_limit`, `astream_events` | G15/G17; 04 | ADR-007 implementation (Step 5) |
| B3 | Prompt engineering for small models: schemas, enums, few-shot from golden data, repair loops, prompt versioning | 04 §3 | extraction eval ≥ 90% field accuracy on nano model |
| B4 | Evals: dataset design, metric choice, noise/tolerance, LLM-as-judge limits; LangSmith datasets/experiments (optional, you have `@traceable` already) | ADR-004 exists; extend | `dataset_extract` + gate (Step 6) |
| B5 | Observability for LLM apps: tracing (LangSmith or OpenTelemetry), token/latency accounting, PII in traces | G13/G14 | traces redact user text by flag; p95 dashboard from JSONL |
| B6 | Failure engineering: timeouts, bounded retries, circuit breaker, idempotency, graceful degradation | 05 §3 rows P9–P12, A4 | termination test + chaos test with a stub that always 429s |
| B7 | System design at *your* scale: sync vs SSE vs jobs; caching; cost budgets | G17 vs SYSTEM-DESIGN-1000 | a one-page "why SSE, not a queue, until N users" note in archdocs |

## Track C — Product front (Flutter) — only what's needed to ship

| # | Learn | Why here | Prove it by |
|---|---|---|---|
| C1 | Riverpod 3: `Notifier`/`AsyncNotifier`, `AsyncValue` states, overrides in tests | skill.md is on Riverpod 2 API (G8) | `meal_provider` with loading/error/data + tests |
| C2 | Flutter testing: widget tests, `ProviderScope` overrides, golden tests | G20 | `DayRing` golden at 5 fill states |
| C3 | Consuming SSE in Dart; cancellation | 04 §6 | stage label under the input bar during a call |

## Track D — Claude Code as an engineering platform (you're already ahead; sharpen)

| # | Learn | Why here | Prove it by |
|---|---|---|---|
| D1 | Hooks (`PreToolUse`/`PostToolUse`/`Stop`) as policy enforcement | G2 | `.env` read is blocked; `dart analyze` auto-runs |
| D2 | Agent design: narrow tools, structured reports, DoD checklists, escalation | G4/G5 | YAML report block in every agent |
| D3 | Skills as single-source specs; generated sections | G8/G9 | API section generated from OpenAPI |
| D4 | Plan mode + briefs before ADRs | G12 | `requirements-brief` skill used once end-to-end |
| D5 | Memory hygiene: what belongs in memory vs docs vs code | AGENT-HANDOFF drift | memory index ≤ 15 lines, each pointing to a doc |

## Suggested pairing per fortnight

| Weeks | Track A | Track B | Repo step |
|---|---|---|---|
| 1–2 | A1, A2, A3 | B1 | Steps 0–2 |
| 3–4 | A4, A6 | B2 (graph basics) | Steps 3–4 |
| 5–6 | A7 | B2 (interrupt/checkpoint), B3 | Step 5 (ADR-007) |
| 7–8 | A5 | B4, B6 | Steps 6, 8 |
| 9–10 | C1–C3 | B5, B7 | Step 7 |

📘 **Learn this — "prove it by" is the whole method.** Every skill above has a repo task
that leaves an artifact (a green CI run, a test file, a tagged release). That is how you
turn learning into a shipped product *and* a portfolio: the artifacts are the proof, and the
run records from `03 §3` are the narrative.

## Reading list (short, high-yield)

- LangGraph docs: "Concepts → Low-level" (state, reducers, persistence, interrupts), then
  "How-tos → Streaming events". Read *after* sketching your graph, not before.
- LangChain docs: structured output + fallbacks/retries pages only.
- FastAPI docs: "Handling Errors", "Middleware", "Settings and Environment Variables", "Testing".
- *Release It!* (Nygard) — chapters on stability patterns (timeouts, bulkheads, circuit breakers).
- Google's "Testing on the Toilet" posts on flaky tests and test sizes (small/medium/large ≈ your L1/L2/L4).
- Anthropic/OpenAI eval cookbooks — for dataset design and judge pitfalls, not for tooling.
