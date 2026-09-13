# 03 — Target SDLC for a production AI product (mapped onto your agents)

The goal: a pipeline where **every gate is a machine check or a checklist**, so it works
whether the stage is run by you, Opus, or a nano model. Your agent roster already fits; this
adds the missing stages, the structured handoff, DoDs, CI, and a release stage.

## 1. The stages

```
 ┌────────────┐  ┌──────────────┐  ┌───────────┐  ┌───────────┐  ┌────────┐  ┌────────┐  ┌─────────┐
 │ Requirements│→│ Architecture │→│ Implement │→│  Test     │→│ Review │→│ Release│→│ Observe │
 │  (brief)   │  │ (ADR)        │  │ (engineer)│  │ (tester)  │  │ (gate) │  │        │  │         │
 └────────────┘  └──────────────┘  └───────────┘  └───────────┘  └────────┘  └────────┘  └─────────┘
      you +          architecture-     backend-/ai-/    tester        reviewer    backend-      logs/evals
   requirements-     designer          ui-/flutter-                   + CI        engineer      feed back
   brief skill       (skip if ADR      engineer                                   + release     into
                     already covers)                                              checklist     Requirements
```

| Stage | Exists today? | Entry criterion | Exit artifact |
|---|---|---|---|
| Requirements | ad hoc (ADR-005 brief was the one good example) | a user ask | `plans/<unit>-brief.md` from template (§2) |
| Architecture | ✅ | brief says "needs a decision not covered by an ADR" | ADR with contracts + per-engineer handoff |
| Implement | ✅ | ADR/spec + brief | code + YAML report (§3) |
| Test | ✅ | engineer report | tests + exceptional-case rows + YAML report |
| Review | ✅ (prompt-only) | tester report | verdict; **CI green is a precondition** |
| Release | ❌ | reviewer pass | tagged version, changelog entry, deploy checklist ticked |
| Observe | partial (traces, eval reports) | shipped | metrics/logs reviewed; new golden cases from real failures |

**Rule for small models:** every arrow above carries a *file*, not a conversation. The next
stage reads the file. Files have templates. Templates have required fields.

## 2. Requirements brief (new skill: `skills/requirements-brief/SKILL.md`)

Template (all sections required; "N/A" is a valid answer, blank is not):

```markdown
# Brief: <unit_id> — <title>
## Problem (1–3 sentences, what breaks/what's missing today)
## Users & trigger (who, doing what)
## In scope / Out of scope (bullets; out-of-scope is mandatory)
## Success criteria (measurable: "p95 < 10 s", "eval MAPE not worse than baseline")
## Constraints (models, cost, latency, platforms, privacy)
## Contract touchpoints (endpoints/schemas/storage keys that may change — name them exactly)
## Open product decisions (each tagged USER-DECIDES; the pipeline stops on these)
## Naming to reuse (existing symbols/files; never invent parallel names)
## Needs an ADR? (yes/no + why)
```

📘 **Learn this — why a brief before an ADR?** An ADR answers *how*; it cannot answer
*what/why*. The frontend integration stalled on six product questions because they were
discovered during planning instead of before it. A brief front-loads the "USER-DECIDES"
items so the pipeline never guesses a product decision.

## 3. Structured handoff report + Definitions of Done

### 3.1 The report every engineer/tester emits (fenced YAML at the end of the report)

```yaml
unit_id: adr007-2b            # from the brief/plan
stage: ai-engineer             # backend-engineer | ai-engineer | ui-engineer | flutter-engineer | tester
files_changed:
  - calai_backend/services/graph.py
contract:
  before: "AgentResponse{response:str, iterations_used:int}"
  after:  "AgentResponse{response:str, iterations_used:int, pipeline_steps_run:list[str]}"
  breaking: false
handoffs:                      # things another agent must do, verbatim
  - to: backend-engineer
    what: "add field to schemas.AgentResponse"
    verbatim: "pipeline_steps_run: list[str] = []"
tests:
  added: [calai_backend/tests/test_graph_router.py]
  run_cmd: "python -m pytest calai_backend/tests -q"
  result: "93 passed"
logging_added: ["router.decision", "handler.outcome"]   # ADR-005 logging contract
open_questions: []             # non-empty ⇒ orchestrator stops and asks
deferred: []                   # explicitly not done, with reason
risk: low                      # low | medium | high + one line why
```

The orchestrator forwards **this block** to the next stage, and appends it to
`artefacts/runs/<date>-<unit_id>.md`.

### 3.2 Definition of Done — engineer (backend/ai/flutter)
- [ ] Analyzer/linter clean on every touched file (`ruff`, `dart analyze lib/<file>`)
- [ ] Contract `before/after` stated; `breaking` answered honestly
- [ ] Every new decision point logs a structured line (`intent`, `handler`, `outcome`, `latency_ms`, correlation id)
- [ ] No new required env var without the key-name check (`dotenv_values(path).keys()`)
- [ ] Any file outside your ownership listed under `handoffs` with verbatim content
- [ ] Docs touched: the skill/ADR section that states the changed fact is updated (or listed in `handoffs` to ui-engineer/architecture-designer)
- [ ] YAML report emitted

### 3.3 Definition of Done — tester
- [ ] For each changed behavior: one test that fails before / passes after (say which)
- [ ] Applicable rows of the exceptional-case matrix (`05` §3) covered or explicitly deferred
- [ ] `pytest` runs with no network (recorded fixtures for model calls)
- [ ] If a prompt/model/extraction changed: golden cases added and `run_eval.py --gate` command included in report
- [ ] Flutter: widget test per changed widget/screen behavior
- [ ] YAML report emitted

### 3.4 Definition of Done — reviewer (gate)
- [ ] CI is green on the branch (or the same commands were run locally and exit codes cited)
- [ ] Contract diff matches the ADR/brief; no unrequested contract change
- [ ] Docs-sync: grep `skills/` + `archdocs/` for any renamed/removed field or route
- [ ] Production lens (security/reliability/cost — `reviewer.md` addition in 08)
- [ ] Logging contract present at decision points
- [ ] Status header of the executed plan/ADR updated
- [ ] Verdict in three buckets; bucket-1 findings each have file:line + failure scenario

## 4. CI (the machine half of the gate)

`.github/workflows/ci.yml` — three jobs:

| Job | Trigger | Steps | Network |
|---|---|---|---|
| `backend` | every push/PR | `pip install -r requirements-dev.txt` → `ruff check` → `python -m pytest calai_backend/tests -q` | none (fixtures) |
| `frontend` | paths `calai_frontend/**` | `flutter pub get` → `dart analyze lib` → `flutter test` | none |
| `evals-gate` | paths `calai_backend/prompts/**`, `services/meal_parse_agent.py`, `services/agent_service.py`, `config.py`, `evals/**` | `python evals/run_eval.py --gate --baseline evals/report/latest.json --tolerance-pct 3` | NIM (secret) |

Local: `pre-commit` with `ruff` + `ruff-format`; `Makefile` targets `test`, `lint`, `eval`,
`run`, so every agent runs the *same* command strings (small models copy commands; give
them one canonical spelling).

📘 **Learn this — path-filtered eval gate.** Live-model evals are slow and cost money; running
them on every push trains people to ignore CI. Run them only when files that can change model
behavior change. The tolerance absorbs sampling noise (the README already measured it).

## 5. Release stage (new; checklist owned by `backend-engineer`)

- [ ] `pydantic-settings` `Settings` class; env precedence documented; startup fails loud on missing `NVIDIA_API_KEY`
- [ ] `Dockerfile` (multi-stage, non-root) + `docker compose` for local run
- [ ] `/api/health` (liveness, no deps) and `/api/ready` (NIM key present; cached cheap ping)
- [ ] `X-Request-ID` in/out; correlation id = request id; JSON logs to stdout
- [ ] `/api/version` returns git SHA + prompt-set version
- [ ] Rate limit + body size limit on LLM endpoints
- [ ] `CHANGELOG.md` entry; git tag `vX.Y.Z`; eval report snapshot copied to `artefacts/releases/vX.Y.Z/`
- [ ] Rollback note: previous tag + how to switch `USE_ORCHESTRATOR`/prompt version

## 6. Observe stage (closes the loop)

- Weekly: read `logs/traces/*.jsonl` for `outcome != ok`; turn real failures into golden cases (tester).
- Track: p50/p95 latency per endpoint, tokens/request, eval metrics per release, fix-loops per unit.
- These numbers feed the next brief's "Success criteria". That is the whole point of the loop.

## 7. Where each of your agents sits after this change

| Agent | Adds |
|---|---|
| `sdlc-orchestrator` | reads brief; refuses to run without one when a product decision is open; writes run record; updates status headers |
| `architecture-designer` | requires brief; per-engineer handoff paragraphs (done) |
| `backend-engineer` | CI/Dockerfile/settings/health/ready/rate-limit/OpenAPI export; error envelope |
| `ai-engineer` | LangGraph runtime (04); logging contract; extraction eval dataset with tester |
| `tester` | exceptional-case matrix; recorded fixtures; Flutter smoke + widget tests |
| `reviewer` | CI-green precondition; docs-sync; production lens; status header check |
| `ui-engineer` | resolves G9 decisions; single-source skill; regenerates API section from OpenAPI |
| `flutter-engineer` | Riverpod 3 patterns; SSE consumption; error/loading states |
