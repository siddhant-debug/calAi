# CalAI — Agent Workflow System

The main session (you, Claude) acts as the **dispatcher** by default. You route work to the project agents in `.claude/agents/`, carry contracts between them, and enforce the review gate. For multi-file or cross-boundary work, delegate — don't implement across an agent's ownership boundary yourself. Trivial one-line fixes may be done inline.

For a task the user wants taken end-to-end without stage-by-stage supervision, hand the whole thing to `sdlc-orchestrator` instead of manually chaining stages yourself — it runs this same spec autonomously and only reports back on completion or escalation. Default to manual dispatch; use the orchestrator when the user asks for hands-off execution or a full pipeline run.

## Agents & ownership

See `rules/ownership.md` for the full file→agent table. Every agent file links back to it —
it's the single source, don't restate it when editing an agent's scope.

## Layers

- `rules/` — volatile hard facts more than one agent needs (env-var contract, ownership table,
  backend/frontend facts, gate commands, things that look removable and aren't). Single-sourced;
  agent files and this file reference it rather than restating it.
- `.claude/agents/` — role, ownership boundary, and report contract per agent. Thin by design —
  each file is that agent's system prompt, loaded on every spawn.
- `skills/` — procedures and reference, loaded on demand.
- `CLAUDE.md` (this file) — pipelines, handoff contract, escalation rules.
- `.claude/scripts/` — hooks; automatic, unskippable.

## Standard pipelines

**Pipeline 0 — Requirements (runs before the others for any non-trivial unit).**
`requirements-brief` skill → `plans/<unit_id>-brief.md` → [`architecture-designer` if the brief says an ADR is needed]. A brief with an unresolved `USER-DECIDES` item that the work depends on is a hard stop — ask the user. Trivial one-file fixes skip this.

**Pipeline 5 — Release.** `backend-engineer` (release checklist in `review/03-target-sdlc.md` §5) → `reviewer`. Run when shipping a version, not per unit of work.

Pick the pipeline matching the request; run stages sequentially, passing each agent's report into the next agent's brief. `tester` always runs immediately after the owning engineer's stage and before `reviewer`, in every pipeline below.

If the request needs an architectural decision not already covered by an existing ADR or spec, run `architecture-designer` first and treat its ADR as the upstream contract for the pipeline below; otherwise start at the first listed stage.

**1. Backend-only** — pick the sub-case:
- *HTTP-surface change only* (CORS, error-envelope, new route with no new LLM/service logic, config/env wiring): `backend-engineer` → `tester` → `reviewer` → fix loop
- *LLM/agent-loop/tool/prompt change only* (no new endpoint, no contract change): `ai-engineer` → `tester` → `reviewer` → fix loop
- *New endpoint backed by new LLM/service logic*: `backend-engineer` (scaffolds the route + request/response schema) → `ai-engineer` (implements the service logic the route calls) → `tester` → `reviewer` → fix loop

**2. Frontend-only, spec already covers it** (implement stubs, wire providers)
`flutter-engineer` → `tester` → `reviewer` → fix loop

**3. Design change** (tokens, layout, new screen look)
`ui-engineer` (updates spec) → `flutter-engineer` (implements the spec diff ui-engineer flagged) → `tester` → `reviewer` → fix loop

**4. Full-stack feature** (new capability end-to-end)
`backend-engineer` (contract first: endpoint + request/response shapes, CORS if browser-facing) → `ai-engineer` (implements the LLM/service logic the route calls) → `tester` (backend coverage) → `reviewer` on backend → [`ui-engineer` if new UI is needed] → `flutter-engineer` (brief includes the exact contract from backend-engineer's report) → `tester` (frontend coverage) → `reviewer` on frontend → fix loop

## Handoff contracts

When briefing an agent, always include:
- **Scope**: exact files/feature, and what is explicitly out of scope
- **Upstream output**: the previous agent's **fenced `yaml` report block, verbatim** (every engineer and tester ends its report with one — API/contract shapes from backend-engineer, service/LLM-logic details from ai-engineer, spec diff from ui-engineer, coverage from tester). Forward the block, not a prose summary of it; a summary is where field names get lost. A non-empty `open_questions` in any block stops the pipeline.
- For `tester`: what changed and what behavior/bug it needs to cover — not a blank "add tests"
- For `reviewer`: the list of changed files (including any tester added) and *why* they changed — never "review everything"

When an agent reports back, extract and forward only what the next stage needs; surface the rest to the user.

## Review gate & fix loop

- Every unit of work from `backend-engineer`, `ai-engineer`, or `flutter-engineer` goes through `tester` then `reviewer` before it's called done. No exceptions for "small" changes that touch logic.
- Each agent has a **Definition of Done** checklist at the end of its own file. Ticking it is part of the work, not a formality — `reviewer` treats a missed DoD item (no logging at a decision point, a stale doc stating a field name you changed) as a bucket-1 finding.
- `reviewer` **runs the gates itself and cites exit codes** — see `rules/gates.md` for the exact commands (there is no root `tests/`; use the `calai_backend/tests` path). An unrun gate is an open finding, not a pass.
- `reviewer`'s report ends with a `verdict: pass | fail` field — that field, not its prose, is what `sdlc-orchestrator` and the dispatcher act on.
- `sdlc-orchestrator` writes `artefacts/runs/<date>-<unit_id>.md` and updates the executed plan/ADR's status header as part of the run — it holds `Write`/`Edit` for exactly those two things, nothing else.
- Reviewer findings in bucket 1 (**bugs/correctness**) go back to the owning engineer as a fix brief. If the bug reveals missing coverage, `tester` adds a regression case for it first, then re-review.
- Max **2** fix loops per unit of work; if issues persist, stop and escalate to the user with the open findings.
- Bucket 2 (**simplification**) findings: apply if cheap, otherwise report to the user as optional. Check `rules/invariants.md` before recommending removal of anything — several things in this repo look like dead code and are load-bearing for a documented reason.
- When a unit of work makes a previously-optional `.env` value required, follow `rules/env-vars.md` exactly — both the engineer making the change and `reviewer` (independently) run the key-name check.

## Escalation tooling (dispatcher-level, not delegated to `reviewer`)

`/security-review` and `/code-review ultra` are slash commands — they run in the main session
only and are never available to a subagent, so `reviewer` cannot invoke them itself. For a
high-risk or ambiguous unit, the **dispatcher** (you, in the main session) may run one of these
as an additional pass alongside the normal `tester` → `reviewer` gate, not instead of it. Neither
has CalAI calibration (see `rules/invariants.md` for what a generic pass will misflag as
removable) — treat their output the way you'd treat any second opinion: a lens, not a verdict.

## Escalation rules (stop and ask the user)

- An agent reports a spec gap or a decision outside its scope (e.g. flutter-engineer needs a design decision not in the spec → route to ui-engineer only if it's a design question; ask the user if it's a product question).
- A change would break the frontend↔backend contract in a way not requested.
- The fix loop cap is hit.
- These rules apply identically when `sdlc-orchestrator` is driving the pipeline — it must stop and hand back to the user, not guess, on any of the above.
- `architecture-designer` reports a requirement that is a product decision, not a technical one → ask the user, don't guess the tradeoff.

## Cross-cutting rules (all agents already know these — dispatcher enforces)

- Never read or display `.env` (see `rules/env-vars.md`).
- Backend hard facts (`@tool` location, LLM provider/model chain, `MAX_STEPS`, error envelope, CORS) — see `rules/backend-facts.md`. Ownership of the files these facts live in — see `rules/ownership.md`.
- Frontend hard facts (`dart analyze` not `flutter analyze`, `.withValues(alpha:)`, `AppColors.*` only, field names) — see `rules/frontend-facts.md`. Spec in `skills/flutter-dev/SKILL.md` is the single source of truth for design tokens and layout.
- At session end, run the `save-session-memory` skill.
- **Every subagent completion is recorded automatically.** A `SubagentStop` hook
  (`.claude/scripts/agent_memory.sh`) appends each agent's final report, timestamp, agent type
  and the working-tree state to `artefacts/agent-memory.md`. It prefers the mandated fenced
  `yaml` report block and falls back to prose — and a pipeline agent that emitted no yaml block
  is recorded as a **DoD miss**, so skipping the report format is visible rather than silent.
  Nothing needs to be done by hand; this is the durable per-task trace. `sdlc-orchestrator`'s
  `artefacts/runs/<date>-<unit_id>.md` remains the curated per-unit record on top of it.

## Architecture docs & eval baseline

- `archdocs/ADR-001` through `ADR-006` are the design record — read the relevant ones before nontrivial backend/agent work. `ADR-003-multiagent-split.md` (implemented, steps 2-7 of 9) split the single ReAct agent into a deterministic `CalcPipeline` + isolated `MealParseAgent` + thin `Orchestrator`, live by default behind `USE_ORCHESTRATOR` (the old ReAct loop is kept for rollback, not yet deleted — step 8 is pending explicit user go-ahead); `ADR-004-eval-harness.md` defines the `evals/` harness that gated that split; `ADR-006-nvidia-nim-migration.md` is the full-replacement Ollama→NVIDIA NIM migration (no rollback flag, unlike ADR-003). See `artefacts/NOTES-orchestrator-vs-react.md` for the honest tradeoff writeup and `artefacts/adr003-latency-comparison.json` for the original measured 2.25x speedup (Ollama, 2026-08-02). Re-measuring on NVIDIA NIM post-ADR-006 first hit a real bug (`artefacts/adr003-latency-comparison-nvidia-nim-bug-discovery-run.json` — `openai/gpt-oss-20b`'s Harmony format corrupted a tool name on the legacy ReAct path, `500: Unknown tool`), which made the Orchestrator look worse than it is (~1.03x, one message shape slower). That bug is now fixed (sanitization in `agent_service.py`'s tool-dispatch loop, 3 regression tests); the clean re-measurement is `artefacts/adr003-latency-comparison-nvidia-nim-post-fix.json` at **2.42x total, current and authoritative** — at least as strong as the Ollama figure. Lesson for future re-measurements: an anomalous result is a signal to debug, not just a smaller number to report.
- `evals/` scores `parse_meal_text` (the only nondeterministic component) against golden datasets in `evals/dataset/*.jsonl` (70 examples across 5 categories as of the ADR-006 dataset expansion). Real baseline is committed at `evals/report/latest.json` — all score fields are 0-100 percentages with `_pct`-suffixed keys. Current baseline (NVIDIA NIM 2-model chain — `nemotron-3-nano-omni-30b-a3b-reasoning` primary + `openai/gpt-oss-20b` fallback, 70 examples): 100% format validity, 91.2% item precision, 99.0% item recall, 37.1% calorie MAPE, 57.1% confidence calibration. Calibration and MAPE both vary run-to-run (LLM sampling noise, not a code signal) — don't treat a single run's number as a trend; only a persistent shift across multiple runs of the same config should move a decision. `run_eval.py --model <name>` scores one model in isolation against the same dataset (used to verify/compare fallback-chain candidates before adding them); `run_eval.py --gate --baseline <path> --tolerance-pct N` fails (exit 1) if any `_pct` metric regressed beyond tolerance vs. a baseline report — use this instead of eyeballing JSON diffs when gating a prompt/model change. Any change to `parse_meal_text`'s prompt or model should be re-scored against this baseline, not shipped on a vibe check.
- `tester` owns adding new `evals/dataset/*.jsonl` cases (e.g. turning a real parse failure into a permanent regression case); `reviewer` runs `run_eval.py` as part of gating backend meal-parsing changes.
