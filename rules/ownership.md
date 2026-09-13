# Rule: file ownership

| Agent | Owns | Never touches |
|---|---|---|
| `architecture-designer` | New ADRs in `archdocs/`, design contracts and migration plans | Implementation code (any language) |
| `backend-engineer` | `calai_backend/main.py`, `api/routes.py`, `config.py`, `schemas.py` — HTTP surface: CORS, request/response envelopes, status codes, boundary validation, env-var wiring | `calai_backend/services/`, `providers/`, `tools/`, `prompts/`, `calai_agent.py` (that's `ai-engineer`), Flutter code, visual design |
| `ai-engineer` | `calai_backend/services/`, `providers/`, `tools/`, `prompts/`, `calai_agent.py`, SQLite meal-schema semantics, agent/LLM logic | The HTTP surface (that's `backend-engineer`), Flutter code, visual design |
| `ui-engineer` | Design tokens, layout, UX spec (`skills/flutter-dev/SKILL.md` spec sections, `archdocs/frontendidea.md`) | `.dart` implementation |
| `flutter-engineer` | `calai_frontend/lib/**/*.dart` | New visual design, backend contracts |
| `tester` | pytest suites, `evals/dataset/*.jsonl` cases (ADR-004), Flutter tests | Gating — doesn't decide pass/fail, doesn't edit product code |
| `reviewer` | Read-only review + running tests/evals as the pass/fail gate | Editing anything |
| `sdlc-orchestrator` | Autonomous pipeline execution; its own run record (`artefacts/runs/`) and status-header updates | Doing engineering/testing/review work directly |

The seam inside `calai_backend/` is `routes.py` calling into `services/`: `backend-engineer` owns
the call and its request/response envelope, `ai-engineer` owns what the called function does.
Neither edits the other's files — the one who needs a change states it verbatim in their report
and hands it over.

Referenced by: `CLAUDE.md`, `ai-engineer.md`, `backend-engineer.md`, `reviewer.md`,
`skills/calai-workflow/SKILL.md`.
