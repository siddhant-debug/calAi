# 02 — Gaps, with evidence and fixes

Each gap: **what** · **evidence (artifact, not code)** · **why it matters for production /
small models** · **fix** · **owner**. Severity legend in `README.md`.
Numbering is stable — `07-action-plan.md` refers to these IDs.

---

## A. Enforcement: rules exist, machines don't enforce them

### G1 🔴 No CI — every gate is "remember to run it"
- **Evidence:** no `.github/workflows/`, no `pre-commit`, no `Makefile`/`pyproject.toml`.
  `CLAUDE.md` says `reviewer` runs `pytest` and `run_eval.py --gate`; nothing runs them if
  the reviewer stage is skipped, or if a human edits directly.
- **Why:** an SDLC whose gates live only in prompts is an SDLC that degrades the moment a
  weaker model, a tired human, or a "quick fix" bypasses the pipeline. The ADR-005 plan itself
  records both fix loops being caused by *test pollution found late* — CI catches that on
  every push, for free.
- **Fix:** GitHub Actions with three jobs: `backend` (ruff + mypy-light + pytest, no network),
  `frontend` (`dart analyze` + `flutter test`), `evals-gate` (runs **only** when
  `calai_backend/prompts/**`, `services/meal_parse_agent.py`, `config.py`, or
  `evals/dataset/**` change; uses `--gate --baseline --tolerance-pct`; needs the NIM key as a
  repo secret). Plus `pre-commit` locally for ruff/format. Details: `03-target-sdlc.md` §4.
- **Owner:** `backend-engineer` (CI/config is HTTP-surface-adjacent infra) → `reviewer`.

### G2 🟠 Cross-cutting rules are prompt-only when they could be hooks
- **Evidence:** "Never read `.env`" appears in `CLAUDE.md`, three agent files, one skill and
  memory. `dart analyze after each file` is a rule in `flutter-engineer.md`. Only hook present:
  `Stop → memory_save_gate.sh`.
- **Why:** repeating a rule in six places is a sign it should be a mechanism. Small models
  forget prompts; they cannot bypass a `PreToolUse` hook that blocks `Read` on `**/.env`.
- **Fix:** three hooks — `PreToolUse` block on reading/catting any `.env*`; `PostToolUse`
  on `Edit|Write` of `calai_frontend/lib/**/*.dart` → run `dart analyze <file>` and surface
  errors; `PostToolUse` on `Edit|Write` of `calai_backend/**/*.py` → `ruff check <file>`.
  Then *delete* the duplicated prose and leave one pointer ("enforced by hook X").
- **Owner:** you (settings), documented by `backend-engineer`.

### G3 🟡 Permissions allowlist is ad hoc
- **Evidence:** `settings.local.json` allows three spellings of the same pytest command.
- **Fix:** allow `Bash(python -m pytest *)`, `Bash(dart analyze *)`, `Bash(flutter test *)`,
  `Bash(ruff *)` once; remove duplicates. (Run `/fewer-permission-prompts` after Step 0.)

---

## B. Handoffs: prose contracts that small models will drift on

### G4 🔴 Agent reports are free-form; downstream agents parse prose
- **Evidence:** every agent ends with "report: what you changed, …" as a sentence. The
  dispatcher/orchestrator must *extract* scope, contract, files, and open questions from
  paragraphs. Today's session found three places where the report instruction had silently
  fallen out of sync with the ownership split (`CLAUDE.md` gate rule, handoff example,
  `ai-engineer` report bullet).
- **Why:** with a capable model, prose works. With a small model doing dispatch, prose is
  where information is dropped. Production pipelines pass **structured artifacts**.
- **Fix:** one report template, same for every engineer, emitted as a fenced YAML block at
  the end of the report (template in `03-target-sdlc.md` §3). Fields: `unit_id`, `stage`,
  `files_changed[]`, `contract{before,after}`, `handoffs[] {to, what, verbatim}`,
  `tests{added[],run_cmd,result}`, `open_questions[]`, `deferred[]`, `risk`. The orchestrator
  forwards the YAML, not the prose.
- **Owner:** you edit agent files (08 has the text).

### G5 🟠 No Definition of Done per stage
- **Evidence:** "before it's called done" appears, but "done" is defined only by "reviewer
  passed". No checklist says what an engineer must have *produced* before handing to tester.
- **Fix:** a DoD checklist per stage (in `03-target-sdlc.md` §3): engineer DoD (analyzer/ruff
  clean, contract stated, logging at decision points, no new env var without the key-name
  check…), tester DoD (red-green shown, exceptional-case matrix rows covered, no network in
  pytest), reviewer DoD (ran the commands, cited exit codes, checked docs-sync).

### G6 🟠 No pipeline run record
- **Evidence:** the ADR-005 plan status is a hand-written paragraph; the only run history is
  memory + `AGENT-HANDOFF.md` (superseded). Nothing records which stages ran, how many fix
  loops, how long, what changed, per unit.
- **Fix:** `sdlc-orchestrator` writes `artefacts/runs/<date>-<unit_id>.md` from the YAML
  reports (stages, loops used, files, verdict). Cheap, greppable, and it becomes your
  "engineering log" for the resume story you're building.

### G7 🟡 Stale status headers are not part of any DoD
- **Evidence:** `plans/adr005-…-plan.md` still says "BLOCKED: Ollama unreachable" though
  ADR-006 removed Ollama weeks ago; `AGENT-HANDOFF.md` needed a "SUPERSEDED" banner.
- **Fix:** orchestrator DoD item: "update the status header of the plan/ADR you executed
  against, in the same run". Reviewer checks it.

---

## C. Docs/skills drift from the code (found without reading code)

### G8 🔴 Contract mismatches in skills that would 422 in production
| Where | Says | Reality (from backend agent's report / routes) |
|---|---|---|
| `skills/flutter-dev/SKILL.md` API facts | `POST /api/parse-meal` body `{"text": …}` | field is `meal_text` (+ optional `meal_type`) |
| `skills/flutter-test/SKILL.md` Step 4 curl | `"activity_level":"moderate"`, `"rate_kg_per_week":0` | enum is `moderately_active`; field is `goal_rate_kg_per_week` (must be `> 0`) |
| `skills/flutter-test/SKILL.md` Step 4 curl | `-d '{"text":"2 eggs and toast"}'` | `meal_text` |
| `skills/flutter-dev/SKILL.md` | Riverpod `^2.5.1`, `StateNotifierProvider` | `pubspec.yaml` is `^3.4.3` — Riverpod 3 uses `Notifier`/`AsyncNotifier` |
| `skills/flutter-dev`, `flutter-test`, `flutter-review` | `flutter analyze` | crashes here; rule is `dart analyze lib/<file>` |
- **Why:** skills are what the *implementing* model reads. A wrong field name in a skill is a
  guaranteed bug delivered confidently. This is the #1 way agent systems ship broken code.
- **Fix:** (a) correct the five items now (`08-agent-and-skill-fixes.md`); (b) stop
  hand-writing API facts — generate the "API contract" section of `flutter-dev/SKILL.md`
  from the backend's OpenAPI (`/openapi.json`) via a tiny script, and make `reviewer` diff it;
  (c) add a **docs-sync check** to reviewer's DoD: "for every changed Pydantic model or route,
  grep skills/ and archdocs/ for the old field name".
- **Owner:** `ui-engineer` (spec text), `backend-engineer` (OpenAPI export script).

### G9 🟠 Skills assert design decisions that are still open
- **Evidence:** `flutter-test` expects "Loading state: button replaced with spinner" and
  "5 rings render for Mon–Fri of current ISO week"; `flutter-review` checks "Weekly totals
  load Mon–Fri of current ISO week (not last 7 days)". Your `scratch/blockers.md` lists ring
  range, loading state, `meal_type` UI and multi-item rendering as **undecided**.
- **Why:** tests and reviews written against undecided behavior either lock in an accident
  or fail forever. Decide first (ui-engineer), then sync all three skills from one source.
- **Fix:** make `skills/flutter-dev/SKILL.md` the *only* place behavior facts live; have
  `flutter-test` and `flutter-review` reference sections by heading instead of restating them.

### G10 🟡 Convention duplication across agents/skills/CLAUDE.md
- **Evidence:** `dart analyze` vs `flutter analyze`; `.withValues` rule only in
  `flutter-engineer.md`; NIM model-verification rule in `CLAUDE.md`, `ai-engineer.md`,
  `calai-workflow`, `reviewer.md`.
- **Fix:** rule of one home: *mechanical* rules → hooks/CI; *tooling* rules →
  the owning agent file; *behavioral* facts → the skill; `CLAUDE.md` links, doesn't restate.

---

## D. SDLC coverage: stages that don't exist yet

### G11 🔴 The pipeline ends at "reviewed", not at "shipped"
- **Evidence:** no stage, agent, or checklist for: environments (dev/staging/prod config),
  secrets handling beyond `.env`, containerization, versioning/changelog, health/readiness
  checks, logging/metrics in production, rollback. `SYSTEM-DESIGN-1000-USERS.md` jumps
  straight to scale.
- **Fix:** add a **Release** stage with a checklist (`03-target-sdlc.md` §5): Dockerfile,
  `pydantic-settings` config with env precedence, `/api/health` (liveness) + `/api/ready`
  (checks NIM key present + one cheap model ping cached), structured JSON logs, request-id
  header, version endpoint, `CHANGELOG.md`, tagged releases. Owner `backend-engineer`.

### G12 🟠 No requirements stage; ADRs sometimes start from loose prose
- **Evidence:** `plans/adr005-requirements-brief.md` is excellent — exact names, dependency
  order, parallel-safe tags — but it was a one-off. The frontend integration went straight to
  a plan and hit six undecided product/UI questions.
- **Fix:** a `requirements-brief` skill (template): problem, users, in/out of scope, success
  metric, constraints, open product decisions (each marked *user decides*), naming to reuse.
  `architecture-designer` refuses to start without one. This is also where small models
  shine — filling a template is easier than inventing structure.

### G13 🟠 Reviewer has one checklist for everything; no security/perf/cost lens
- **Evidence:** reviewer checks conventions + correctness + runs tests. No item for: input
  size limits, prompt-injection handling in `meal_text`, secrets in logs, PII in trace files
  (`logs/traces/*.jsonl` persist raw user text), latency/cost budget per endpoint.
- **Fix:** add a short **Production lens** section to `reviewer.md` (text in 08): security
  (limits, injection, secrets/PII in logs & traces), reliability (timeouts, retries bounded,
  fallbacks tested), cost/latency (p50/p95 vs budget, tokens per request logged).

### G14 🟡 Observability is designed (ADR-005 logging contract) but not gated in reviews yet
- **Evidence:** the ADR-005 plan's logging requirement is strong (structured fields,
  correlation id, WARNING on suspicious values). It applies "to every phase below" — but it's
  in the plan, not in `reviewer.md`'s checklist, so it dies with the plan.
- **Fix:** move the logging contract into `reviewer.md` + `ai-engineer.md` as a standing rule.

---

## E. The app's agent architecture

### G15 🔴 ADR-005 is reinventing LangGraph by hand
- **Evidence:** ADR-005 defines `Intent` enum, `StepResult` (`StepOk | NeedsMoreInfo`),
  `Handler` protocol + `HandlerContext`, `HANDLERS: dict[Intent, Handler]`, bounded ReAct
  fallback (`REACT_FALLBACK_MAX_STEPS = 3`), correlation ids, trace records. That is, almost
  one-to-one: LangGraph `StateGraph` with a typed state, a router node with conditional edges,
  handler nodes, `interrupt()` for "needs more info", `create_react_agent` with
  `recursion_limit` as a subgraph, a checkpointer, and LangSmith tracing.
- **Why:** hand-rolled = you maintain the state machine, persistence, retries, streaming and
  debugging views yourself; LangGraph = you get them, plus a pattern you can reuse in the next
  three products. Your stated goal is exactly that reusability.
- **Fix:** ADR-007 "Orchestrator on LangGraph" (design in
  `04-agent-architecture-langgraph.md`) that *implements* ADR-005's contracts on LangGraph
  instead of a bespoke registry. Keep ADR-005's typed contracts and logging requirement — they
  are right; change the runtime.

### G16 🟠 Half the LLM surface is unmeasured; the calibration signal is known-bad
- **Evidence:** `NOTES` + eval README: `extract_request_fields` has no eval; confidence
  calibration was 39.6% (inverted), now 57.1% (barely signal); dataset `dataset_intent/`
  exists but isn't part of the gate.
- **Fix:** golden dataset for extraction (10–20 messages → expected `ParsedRequest`), scored
  by exact-field match; gate it. Either fix calibration (prompt + eval) or drop the field from
  the contract until it means something — don't ship a UI on it.

### G17 🟠 The 9–40 s synchronous call has no product answer
- **Evidence:** blockers.md #9; no streaming/SSE anywhere; no async job design short of the
  1000-user doc.
- **Fix:** LangGraph `astream_events` → an SSE endpoint (`GET /api/agent/stream`) emitting
  `stage` events (`extracting` → `parsing` → `composing`) and the final payload. This is the
  cheap, correct answer for small scale and it gives the UI something to render. Design in 04.

---

## F. Testing and evals

### G18 🟠 No exceptional-case matrix; tests are happy-path + "bugs we found"
- **Evidence:** `tester.md` says "only for what the code currently does or a concrete bug".
  Good discipline against speculation — but there is no *required* list of boundary cases
  per endpoint (empty/huge input, non-food text, Hinglish, injection, 429/timeout from NIM,
  malformed model JSON, partial JSON, unknown enum).
- **Fix:** the matrix in `05-testing-and-evals.md` §3 becomes a tester DoD input: each new
  endpoint/handler ships with the rows that apply.

### G19 🟠 Component tests hit the network or don't exist
- **Evidence:** tester rule "mock/stub the LLM" for harness tests; nothing describes
  *recorded* fixtures for service-level tests, so the middle of the pyramid (route → service →
  provider with a real-shaped model response) is thin.
- **Fix:** recorded-response fixtures (VCR-style cassettes or JSON fixtures per prompt
  version) so `pytest` covers the full path offline; evals remain the only live calls.

### G20 🟠 Frontend has no working test baseline
- **Evidence:** `test/widget_test.dart` is the default counter template and fails.
- **Fix:** replace with a smoke test now; widget tests per `flutter-test` after decisions
  in G9 are made; add `flutter test` to CI (G1).

---

## G. Frontend integration (already documented; linked for completeness)

See `scratch/blockers.md` — CORS (🔴), error-envelope inconsistency, silent config failure,
and six UI decisions. Those feed Step 4 and Step 7 of the action plan; not repeated here.

---

📘 **Learn this — "enforced vs. remembered".** The recurring pattern in A–C is the same:
a rule stated in prose that a machine could check. The professional reflex is to ask, for
every rule you write down, "what would make it impossible to violate?" Hooks, CI, schema
validation, generated docs. Prose is for judgment calls; mechanisms are for invariants.
