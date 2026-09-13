# 01 — Current state: what exists, and what is genuinely strong

This is an inventory, not a critique. Gaps are in `02-gaps.md`. Read this first so the
critique lands on an accurate picture — several things here are *better* than typical.

## A. The SDLC agents (`.claude/agents/`)

| Agent | Role | Tools | Report contract (what it hands downstream) |
|---|---|---|---|
| `architecture-designer` | Requirement → ADR in `archdocs/` | Read/Write/Edit/Grep/Glob | ADR path + number + per-engineer handoff brief |
| `backend-engineer` (new, 2026-09-13) | HTTP surface: `main.py`, `api/routes.py`, `config.py`, `schemas.py` | +Bash | files changed, exact contract before/after, consumer notes |
| `ai-engineer` | LLM/agent internals: `services/`, `providers/`, `tools/`, `prompts/`, `calai_agent.py` | +Bash | files changed, contract consumed/exposed, verbatim code for backend-engineer's files |
| `ui-engineer` | Design tokens/spec in `skills/flutter-dev/skill.md`, `archdocs/frontendidea.md` | no Bash | spec sections changed + which `.dart` files must change |
| `flutter-engineer` | `calai_frontend/lib/**/*.dart` | +Bash | files changed, analyzer status, deferred decisions |
| `tester` | pytest, `evals/dataset/*.jsonl`, Flutter tests; never gates | +Bash | files added, behavior each covers, what's left uncovered |
| `reviewer` | Read-only gate; runs tests/evals; 3-bucket report | Read/Bash/Grep/Glob | bugs / simplifications / looks-good |
| `sdlc-orchestrator` | Runs pipelines autonomously; only Agent + read tools | Read/Grep/Glob/Agent | stage sequence, per-stage outputs, escalation question |

✅ **Strengths worth protecting**
- **Narrow tool grants.** `ui-engineer` and `architecture-designer` cannot run Bash;
  `reviewer` cannot edit; `sdlc-orchestrator` cannot do work itself. This is real least-privilege
  and it is exactly how you keep a small model from "helpfully" doing the wrong job.
- **Explicit "never touches" columns** and a defined seam (`routes.py` → `services/`).
- **Tester/reviewer separation** (writer vs gate) — most teams conflate these.
- **Fix-loop cap = 2 and hard-stop escalation rules.** Bounded loops are the single most
  important property for autonomous agents; you have it.
- **Report contracts exist at all** — every agent ends with "when you finish, report: …".

## B. The workflow spec (`CLAUDE.md`)

- Four named pipelines (backend-only ×3 sub-cases, frontend-only, design change, full-stack).
- Handoff-contract rules (scope, upstream output verbatim, tester/reviewer briefing rules).
- Review gate + fix loop + escalation rules + cross-cutting rules.
- Eval baseline and "re-score prompt/model changes, never vibe-check" rule.
- Env-var contract check codified (module-anchored `load_dotenv`, key-name verification).

✅ This file is doing the job of a team's engineering handbook. Keep it the single spec.

## C. Skills (`skills/`)

| Skill | Purpose | State |
|---|---|---|
| `calai-workflow` | Backend map, tool-adding checklist, NIM debugging table, run/test commands | Mostly current (post-ADR-006) |
| `flutter-dev` | Full frontend spec: implementation order, API facts, design system, coding rules | **Stale in 4 places** (see `02-gaps.md` G7) |
| `flutter-test` | Widget-test inventory, manual golden path, curl connectivity check | **Stale/contradictory in 3 places** |
| `flutter-review` | Review checklist (correctness/simplicity/conventions/architecture) | Stale in 2 places |

✅ The design-system section of `flutter-dev` is unusually precise (tokens, typography,
270° ring geometry, thresholds). That precision is what lets a weak model implement it.

## D. Design record (`archdocs/`)

- ADR-001 (architecture) → ADR-002 (ReAct) → ADR-003 (orchestrator split, measured 2.05–2.41×
  faster, found a real arithmetic bug) → ADR-004 (eval harness) → ADR-005 (router/handler
  registry, Phase 0/1 done, 2a gate open) → ADR-006 (NIM migration, committed).
- `NOTES-orchestrator-vs-react.md` is a model of honest engineering writing: it re-read its
  own claims, corrected one, sharpened two, found a regression it had missed.
- `RESEARCH-indian-nutrition-data.md` is a research-only input to a future ADR-007.
- `SYSTEM-DESIGN-1000-USERS.md` is aspirational and conflicts with the live contract (known).

✅ The ADR discipline (Context → Non-Goals → Decision with concrete contracts → Options with
real rejected alternatives → Consequences → checklist Action Items) is production-grade.

## E. Evals (`evals/`)

- 70 golden examples across 5 category files; per-category + pooled report; `_pct` metrics.
- `run_eval.py --gate --baseline --tolerance-pct` → exit 1 on regression. **This is a real
  quality gate**, and the README explains noise vs signal and dataset-size effects.
- `--model <id>` for isolated model comparison; `latency_comparison.py` for A/B latency.
- Known limits documented: only `parse_meal_text` is scored; `extract_request_fields`
  (half the LLM surface) is unmeasured; confidence calibration is a known-bad signal.

## F. Mechanics (`.claude/settings*.json`, hooks, CI)

- One hook: `Stop` → `memory_save_gate.sh` (session memory).
- Local permissions pre-allow `dart analyze`, `python`, `pytest` variants.
- **No CI workflow, no pre-commit, no `pyproject.toml`, no Dockerfile, no Makefile.**
  Quality is currently enforced by *agents remembering to run things*.

## G. Where the project actually is (from artifacts)

- Backend: 4 endpoints, orchestrator live by default, NIM provider, eval baseline committed.
- ADR-005: 2a implemented, reviewer gate not closed, plan status header stale ("blocked on
  Ollama" — no longer true).
- Frontend: visual mockup; 7 integration files are 0 bytes; no real tests; not wired.
- Integration plan + blockers already written (`scratch/blockers.md`, plan file) — design
  decisions pending.

📘 **Learn this — why an inventory first?** Reviews that start from "what's wrong" produce
churn: they fix things that were deliberate and miss the load-bearing parts. Production
engineering starts by naming invariants worth protecting (the ✅ items) so later changes
don't erode them. You will use the same habit when reviewing a PR or an incident.
