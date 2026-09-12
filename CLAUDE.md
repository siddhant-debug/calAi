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
- When a unit of work makes a previously-optional `.env` value required (an API key with no default/fallback), the owning engineer must (1) use an explicit, module-directory-anchored `load_dotenv()` path, never the bare cwd-dependent default — this repo has more than one `.env` file at different directory levels and the default resolves to whichever one `find_dotenv()` hits first walking up from cwd, not necessarily the intended one; and (2) confirm the exact env var NAME the code reads matches what's actually in the target `.env`, via `dotenv_values(path).keys()` (names only — never values, never the file's raw contents). `reviewer` must independently re-run that same key-name check as part of gating any change that adds a required credential; checking key existence with `os.getenv()` alone is not sufficient, since it can't distinguish "unset" from "set under a different name" and both must be ruled out. This check is compatible with "never read or display `.env`" below since no secret value is ever printed or read.

## Escalation rules (stop and ask the user)

- An agent reports a spec gap or a decision outside its scope (e.g. flutter-engineer needs a design decision not in the spec → route to ui-engineer only if it's a design question; ask the user if it's a product question).
- A change would break the frontend↔backend contract in a way not requested.
- The fix loop cap is hit.
- These rules apply identically when `sdlc-orchestrator` is driving the pipeline — it must stop and hand back to the user, not guess, on any of the above.
- `architecture-designer` reports a requirement that is a product decision, not a technical one → ask the user, don't guess the tradeoff.

## Cross-cutting rules (all agents already know these — dispatcher enforces)

- Never read or display `.env`.
- Backend: tools in `calai_backend/tools/` are plain functions; `@tool` wrappers live in `api/routes.py`. As of ADR-006, the chat LLM provider is NVIDIA NIM (`ChatNVIDIA`), not Ollama — `config.py`'s `LLM_MODELS` is a retry+fallback chain (currently 2 models; verify any candidate model ID against a real call before adding it to the chain, since the NIM catalog's own `deprecated` flag has been found unreliable — see `providers/llm.py`'s comment). `NVIDIA_API_KEY` is required, no local-model fallback. `MAX_STEPS = 8` applies to the legacy ReAct loop only (`USE_ORCHESTRATOR=false`).
- Frontend: `dart analyze lib/<file>` (never `flutter analyze`), `.withValues(alpha:)`, `AppColors.*` only, spec in `skills/flutter-dev/skill.md` is the single source of truth.
- At session end, run the `save-session-memory` skill.

## Architecture docs & eval baseline

- `archdocs/ADR-001` through `ADR-006` are the design record — read the relevant ones before nontrivial backend/agent work. `ADR-003-multiagent-split.md` (implemented, steps 2-7 of 9) split the single ReAct agent into a deterministic `CalcPipeline` + isolated `MealParseAgent` + thin `Orchestrator`, live by default behind `USE_ORCHESTRATOR` (the old ReAct loop is kept for rollback, not yet deleted — step 8 is pending explicit user go-ahead); `ADR-004-eval-harness.md` defines the `evals/` harness that gated that split; `ADR-006-nvidia-nim-migration.md` is the full-replacement Ollama→NVIDIA NIM migration (no rollback flag, unlike ADR-003). See `artefacts/NOTES-orchestrator-vs-react.md` for the honest tradeoff writeup and `artefacts/adr003-latency-comparison.json` for the original measured 2.25x speedup (Ollama, 2026-08-02). Re-measuring on NVIDIA NIM post-ADR-006 first hit a real bug (`artefacts/adr003-latency-comparison-nvidia-nim-bug-discovery-run.json` — `openai/gpt-oss-20b`'s Harmony format corrupted a tool name on the legacy ReAct path, `500: Unknown tool`), which made the Orchestrator look worse than it is (~1.03x, one message shape slower). That bug is now fixed (sanitization in `agent_service.py`'s tool-dispatch loop, 3 regression tests); the clean re-measurement is `artefacts/adr003-latency-comparison-nvidia-nim-post-fix.json` at **2.42x total, current and authoritative** — at least as strong as the Ollama figure. Lesson for future re-measurements: an anomalous result is a signal to debug, not just a smaller number to report.
- `evals/` scores `parse_meal_text` (the only nondeterministic component) against golden datasets in `evals/dataset/*.jsonl` (70 examples across 5 categories as of the ADR-006 dataset expansion). Real baseline is committed at `evals/report/latest.json` — all score fields are 0-100 percentages with `_pct`-suffixed keys. Current baseline (NVIDIA NIM 2-model chain — `nemotron-3-nano-omni-30b-a3b-reasoning` primary + `openai/gpt-oss-20b` fallback, 70 examples): 100% format validity, 91.2% item precision, 99.0% item recall, 37.1% calorie MAPE, 57.1% confidence calibration. Calibration and MAPE both vary run-to-run (LLM sampling noise, not a code signal) — don't treat a single run's number as a trend; only a persistent shift across multiple runs of the same config should move a decision. `run_eval.py --model <name>` scores one model in isolation against the same dataset (used to verify/compare fallback-chain candidates before adding them); `run_eval.py --gate --baseline <path> --tolerance-pct N` fails (exit 1) if any `_pct` metric regressed beyond tolerance vs. a baseline report — use this instead of eyeballing JSON diffs when gating a prompt/model change. Any change to `parse_meal_text`'s prompt or model should be re-scored against this baseline, not shipped on a vibe check.
- `tester` owns adding new `evals/dataset/*.jsonl` cases (e.g. turning a real parse failure into a permanent regression case); `reviewer` runs `run_eval.py` as part of gating backend meal-parsing changes.
