# CalAI — Agent Workflow System

The main session (you, Claude) acts as the **dispatcher** by default. You route work to the project agents in `.claude/agents/`, carry contracts between them, and enforce the review gate. For multi-file or cross-boundary work, delegate — don't implement across an agent's ownership boundary yourself. Trivial one-line fixes may be done inline.

For a task the user wants taken end-to-end without stage-by-stage supervision, hand the whole thing to `sdlc-orchestrator` instead of manually chaining stages yourself — it runs this same spec autonomously and only reports back on completion or escalation. Default to manual dispatch; use the orchestrator when the user asks for hands-off execution or a full pipeline run.

## Agents & ownership

| Agent | Owns | Never touches |
|---|---|---|
| `architecture-designer` | New ADRs in `archdocs/`, design contracts and migration plans | Implementation code (any language) |
| `ai-engineer` | `calai_backend/`, `calai_agent.py`, prompts, SQLite schema, agent/LLM logic | Flutter code, visual design |
| `ui-engineer` | Design tokens, layout, UX spec (`skills/flutter-dev/skill.md` spec sections, `archdocs/frontendidea.md`) | `.dart` implementation |
| `flutter-engineer` | `calai_frontend/lib/**/*.dart` | New visual design, backend contracts |
| `tester` | Writes/maintains pytest suites, `evals/dataset/*.jsonl` cases (ADR-004), Flutter tests | Gating — doesn't decide pass/fail, doesn't edit product code |
| `reviewer` | Read-only review + running tests/evals as the pass/fail gate | Editing anything |
| `sdlc-orchestrator` | Autonomous end-to-end pipeline execution (spawns the above stages itself) | Doing engineering/testing/review work directly |

## Standard pipelines

Pick the pipeline matching the request; run stages sequentially, passing each agent's report into the next agent's brief. `tester` always runs immediately after the owning engineer's stage and before `reviewer`, in every pipeline below.

If the request needs an architectural decision not already covered by an existing ADR or spec, run `architecture-designer` first and treat its ADR as the upstream contract for the pipeline below; otherwise start at the first listed stage.

**1. Backend-only** (new tool, endpoint, agent-loop change)
`ai-engineer` → `tester` → `reviewer` → fix loop (below)

**2. Frontend-only, spec already covers it** (implement stubs, wire providers)
`flutter-engineer` → `tester` → `reviewer` → fix loop

**3. Design change** (tokens, layout, new screen look)
`ui-engineer` (updates spec) → `flutter-engineer` (implements the spec diff ui-engineer flagged) → `tester` → `reviewer` → fix loop

**4. Full-stack feature** (new capability end-to-end)
`ai-engineer` (contract first: endpoint + request/response shapes) → `tester` (backend coverage) → `reviewer` on backend → [`ui-engineer` if new UI is needed] → `flutter-engineer` (brief includes the exact contract from ai-engineer's report) → `tester` (frontend coverage) → `reviewer` on frontend → fix loop

## Handoff contracts

When briefing an agent, always include:
- **Scope**: exact files/feature, and what is explicitly out of scope
- **Upstream output**: the previous agent's report verbatim (API shapes from ai-engineer, spec diff from ui-engineer, coverage added by tester)
- For `tester`: what changed and what behavior/bug it needs to cover — not a blank "add tests"
- For `reviewer`: the list of changed files (including any tester added) and *why* they changed — never "review everything"

When an agent reports back, extract and forward only what the next stage needs; surface the rest to the user.

## Review gate & fix loop

- Every unit of work from `ai-engineer` or `flutter-engineer` goes through `tester` then `reviewer` before it's called done. No exceptions for "small" changes that touch logic.
- Reviewer findings in bucket 1 (**bugs/correctness**) go back to the owning engineer as a fix brief. If the bug reveals missing coverage, `tester` adds a regression case for it first, then re-review.
- Max **2** fix loops per unit of work; if issues persist, stop and escalate to the user with the open findings.
- Bucket 2 (**simplification**) findings: apply if cheap, otherwise report to the user as optional.

## Escalation rules (stop and ask the user)

- An agent reports a spec gap or a decision outside its scope (e.g. flutter-engineer needs a design decision not in the spec → route to ui-engineer only if it's a design question; ask the user if it's a product question).
- A change would break the frontend↔backend contract in a way not requested.
- The fix loop cap is hit.
- These rules apply identically when `sdlc-orchestrator` is driving the pipeline — it must stop and hand back to the user, not guess, on any of the above.
- `architecture-designer` reports a requirement that is a product decision, not a technical one → ask the user, don't guess the tradeoff.

## Cross-cutting rules (all agents already know these — dispatcher enforces)

- Never read or display `.env`.
- Backend: tools in `calai_backend/tools/` are plain functions; `@tool` wrappers live in `api/routes.py`. `config.py` defaults `MODEL_NAME` to `qwen2.5:7b`, but only `qwen2.5:3b` is actually pulled on the reachable Ollama instance as of 2026-08-01 — confirm which model is live before assuming the config default is what's running (`curl localhost:11434/api/tags`). `MAX_STEPS = 8`.
- Frontend: `dart analyze lib/<file>` (never `flutter analyze`), `.withValues(alpha:)`, `AppColors.*` only, spec in `skills/flutter-dev/skill.md` is the single source of truth.
- At session end, run the `save-session-memory` skill.

## Architecture docs & eval baseline

- `archdocs/ADR-001` through `ADR-004` are the design record — read the relevant ones before nontrivial backend/agent work. `ADR-003-multiagent-split.md` (implemented, steps 2-7 of 9) split the single ReAct agent into a deterministic `CalcPipeline` + isolated `MealParseAgent` + thin `Orchestrator`, live by default behind `USE_ORCHESTRATOR` (the old ReAct loop is kept for rollback, not yet deleted — step 8 is pending explicit user go-ahead); `ADR-004-eval-harness.md` defines the `evals/` harness that gated that split. See `artefacts/NOTES-orchestrator-vs-react.md` for the honest tradeoff writeup and `artefacts/adr003-latency-comparison.json` for the measured 2.25x speedup.
- `evals/` scores `parse_meal_text` (the only nondeterministic component) against golden datasets in `evals/dataset/*.jsonl`. Real baseline is committed at `evals/report/latest.json` — all score fields are 0-100 percentages with `_pct`-suffixed keys. Current baseline (`qwen2.5:3b`, 33 examples): 100% format validity, 83.6% item precision, 92.0% item recall, 59.3% calorie MAPE, 39.6% confidence calibration (below the 50% no-signal line — confidence is not yet a trustworthy signal, don't gate anything on it until this improves). Any change to `parse_meal_text`'s prompt or model should be re-scored against this baseline via `python evals/run_eval.py`, not shipped on a vibe check.
- `tester` owns adding new `evals/dataset/*.jsonl` cases (e.g. turning a real parse failure into a permanent regression case); `reviewer` runs `run_eval.py` as part of gating backend meal-parsing changes.
