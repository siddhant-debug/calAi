# 07 — Action plan: steps, owners, acceptance criteria

Rules: one step at a time; each step ends with a run record; each step teaches one thing.
Gap IDs refer to `02-gaps.md`. "Pipeline" = which `CLAUDE.md` pipeline runs it.

| Step | Name | Closes | Owner(s) / pipeline | Acceptance (machine-checkable where possible) | You learn |
|---|---|---|---|---|---|
| 0 | Mechanical foundations | G1, G2, G3 | you + `backend-engineer` → `reviewer` | `pyproject.toml` + `ruff` + `pre-commit` installed; `Makefile` (`lint/test/eval/run`); CI `backend` + `frontend` jobs green; hooks: `.env` read blocked, `dart analyze` + `ruff` on edit; duplicated prose rules replaced by "enforced by hook/CI" pointers | A1, A2, D1 |
| 1 | Structured handoffs + DoD | G4, G5, G6, G7 | you (agent files) | every engineer/tester/reviewer file ends with the YAML template + DoD; orchestrator writes `artefacts/runs/*.md` and updates status headers; dry-run on a trivial unit produces a run record | D2 |
| 2 | Docs-sync | G8, G9, G10 | `ui-engineer` (spec text), `backend-engineer` (OpenAPI export script) → `reviewer` | the five mismatches fixed (08); `scripts/export_openapi.py` writes `archdocs/api-contract.md`; `flutter-dev/SKILL.md` API section is a pointer to it; reviewer DoD has docs-sync item; UI decisions from `scratch/blockers.md` recorded in skill.md (or marked USER-DECIDES) | D3 |
| 3 | Close ADR-005 Phase 2a gate | (pending work) | `reviewer` | `run_eval.py --gate --baseline evals/report/latest.json --tolerance-pct 3` exit 0; plan status header updated; run record written | B4 |
| 4 | Backend hygiene blockers | blockers 1/1b/1c, G13 | `backend-engineer` → `tester` → `reviewer` (backend-only, HTTP sub-case) | CORS via `allow_origin_regex`; one exception handler → single envelope (test P1, C3 shapes identical); `pydantic-settings` with loud startup failure on missing key; request-id middleware; contract tests L3 green | A4 |
| 5 | Harden `/api/parse-meal` (no new framework) | G15 (scope correction), G17, blockers 1b | `ai-engineer` (structured output + repair-with-feedback, Python-side `total_kcal` sum) → `backend-engineer` (typed-error envelope, optional SSE route) → `tester` → `reviewer` | `with_structured_output` + enums; repair retry feeds the `ValidationError` text back; `total_kcal` summed in Python not trusted from the model; L2 fixture tests for malformed/unknown-enum/non-food; eval gate still ≥ baseline; `/api/agent` marked experimental and excluded from the frontend contract doc | B1, B3, B6 |
| 5a | LangGraph as a measured comparison arm | G15 (methodology), architecture-comparison goal | `requirements-brief` → `architecture-designer` (ADR-007) → `ai-engineer` → `tester` → `reviewer` | `AGENT_RUNTIME` flag with both arms live (nothing deleted); identical contract both ways; **predictions written down before measuring** (`04` §2.5); latency ≥3 runs median per request shape; eval flat (any movement = arm bug); tokens + LOC recorded; fault-injection comparison; honest writeup in `artefacts/` including what didn't improve | B2, B4 |
| 5b | ADR-008: IFCT grounding on LangGraph | G15 (real trigger), G16 | `requirements-brief` → `architecture-designer` → `ai-engineer` → `tester` → `reviewer` | `StateGraph`: decompose (LLM) → IFCT lookup (deterministic) → sum (deterministic); behind `USE_IFCT_GROUNDING` (default off); node + edge tests without a model; `astream_events` → SSE stage events; **calorie MAPE improves vs baseline** (that's the whole point) with `--gate` proving no item-precision regression | B2 (properly), B4 |
| 6 | Test depth | G18, G19, G20 | `tester` → `reviewer` | matrix rows in `05 §3` covered/deferred with reasons; recorded fixtures per prompt version; `pytest --cov` ≥ 85%; Flutter smoke test replaces counter test; CI `evals-gate` job path-filtered and green | A3, B4 |
| 7 | Frontend integration | (existing plan) | `ui-engineer` (decide G9) → `flutter-engineer` → `tester` → `reviewer` (design change + frontend-only) | per `~/.claude/plans/peaceful-roaming-hamster.md` Steps 1–7; SSE stage label; Riverpod 3 Notifiers; widget tests F1–F6 | C1–C3 |
| 8 | Release v0.1.0 | G11, G14 | `backend-engineer` → `reviewer` | Release checklist (`03 §5`) all ticked; Docker compose up serves backend + Flutter web; `/api/ready`; JSON logs with request id; `CHANGELOG.md`; tag; eval snapshot in `artefacts/releases/v0.1.0/` | A5, A6, A7, B5 |
| 9 | Observe loop | — | you + `tester` | weekly: `jq` over traces → 3 new golden cases from real failures; p95 + cost recorded in `artefacts/metrics.md`; next brief's success criteria reference them | B5, B7 |
| 10 | Headless CI agent lane | G1 (deepens), process tooling | you (it's tooling, not product — no CalAI agent owns it) | a non-interactive agent that runs on PR: reads the diff, runs `make lint test`, applies `reviewer.md`'s checklist, posts findings as a PR comment; cost-capped; deterministic enough to re-run; **never gates alone** — it advises, CI gates. Built on the Claude Agent SDK (natural fit: tools + file access) or LangGraph (if you want the state-machine practice). See `09-sdlc-runtime-choice.md` §4 | D2, B2, A2 |

## Sequencing notes

- **0 → 1 → 2 first, even though they feel like chores.** They make every later step cheaper
  and are what a hiring manager means by "production experience". Each is ≤ 1 day.
- **3 before 5:** close the open gate so ADR-007 starts from a known baseline.
- **4 before 7:** CORS/envelope must exist before any browser call.
- **5 before 7:** the frontend consumes `/api/parse-meal`'s error envelope and (optionally) its
  stream, so land the backend shape first.
- **5b is optional and can wait until after v0.1.0.** It's the accuracy play (37.1% calorie
  MAPE is the product's weakest number) *and* the real LangGraph lesson. Don't let it block
  shipping — but do it before adding any UI that displays macros as if they were accurate.
- **10 comes last** — a review bot is only useful once `make lint test` and CI (Step 0) exist
  for it to run, and once `reviewer.md` has the production lens (Step 1) for it to apply.

## Small-model operating rule (applies to every step)

When a step is dispatched to a nano/Haiku-class subagent: give it (1) the brief or ADR
section, (2) the YAML template, (3) the DoD checklist, (4) the exact commands from the
`Makefile`. Do not give it the whole `CLAUDE.md` — give it the pointer and the three files it
needs. Small models fail on *volume*, not on difficulty.

📘 **Learn this — the plan is the product's first test.** If a step's acceptance criterion
can't be written as a command + expected exit code or a file that must exist, the step isn't
ready. Rewrite the criterion, not the code.
