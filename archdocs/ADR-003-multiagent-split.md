# ADR-003: Split the Single ReAct Agent into a Multiagent Pipeline

**Status:** Implemented (steps 2-7 of 9) — Orchestrator live behind `USE_ORCHESTRATOR` flag (default on), old ReAct loop intact for rollback; step 8 (deleting the old path) and step 9 (marking ADR-002 superseded) awaiting explicit user go-ahead
**Date:** 2026-08-01
**Deciders:** Siddhant Tomar
**Companions:** ADR-001 (system architecture), ADR-002 (single-agent ReAct design, current implementation), ADR-004 (eval harness — a prerequisite, see below)

---

## Context

ADR-002 implemented a single ReAct agent (`services/agent_service.py::run_agent`) that binds all tools — `calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal`, `parse_meal_text` (and the still-unimplemented `get_daily_summary`, `save_meal`) — to one LLM and lets it decide the call order each turn.

This works, but the tools fall into two categories that behave nothing alike:

| | Deterministic tools | LLM tool |
|---|---|---|
| Tools | `calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal` | `parse_meal_text` |
| Output | Exact, reproducible, testable with plain assertions | Probabilistic — same input can yield different extracted items/quantities across runs |
| Failure mode | Raises `ValueError` on bad input (422) | Silently wrong (hallucinated calories, missed items) — no exception, no signal |
| Needs eval? | No — unit tests suffice | Yes — this is the actual "AI quality" surface of the product |

Bundling both categories behind one agent has three concrete costs today:

1. **No quality signal on the part that actually needs one.** The deterministic tools can't drift (a formula doesn't degrade), but `parse_meal_text` can, silently, on every model/prompt change. Right now nothing measures that. This is the direct motivation for ADR-004.
2. **Wasted LLM steps on arithmetic the agent doesn't need to reason about.** The system prompt (ADR-002) already hardcodes the rule "always call calculate_bmr before calculate_tdee before calculate_calorie_goal" — i.e. we're using an LLM's step budget (`MAX_STEPS=8`) to walk a fixed, known sequence. That's solved better by code than by prompting.
3. **Blast radius of a bad meal-parse is unbounded.** A hallucinated `parse_meal_text` result flows straight into `save_meal` with no checkpoint, because there is only one agent making one linear decision chain — nothing structurally sits between "LLM produced JSON" and "JSON is trusted."

**Why this matters for the project's stated goal (resume-quality, evaluable AI work):** "I orchestrated multiple tools with an LLM" is a weaker claim than "I identified which part of my system was actually nondeterministic, isolated it behind an evaluated agent, and kept the deterministic 90% of the pipeline as plain code with unit tests." The second claim requires the split described below.

---

## Non-Goals

- This is **not** "split into agents because multiagent is trendy." If a stage has no decision to make, it stays a plain function call, not an agent.
- This does not change any API contract Flutter consumes (`/api/agent`, `/api/parse-meal`, `/api/calculate` keep their existing request/response shapes — see ADR-002 API Surface). The split is internal to `services/`.
- This does not introduce a new LLM-to-LLM messaging protocol, a message bus, or async job queues. Given the load profile in `SYSTEM-DESIGN-1000-USERS.md` (~0.17 RPS peak), that complexity buys nothing yet.

---

## Decision

Split `run_agent` into three collaborators, replacing the single flat tool-bound agent:

```
Orchestrator (plain Python, no LLM)
      │
      ├─► CalcPipeline           — calculate_bmr → calculate_tdee → calculate_calorie_goal
      │                            deterministic, no LLM, no agent loop, just sequential calls
      │
      ├─► MealParseAgent         — the ONLY component that calls an LLM
      │                            wraps parse_meal_text, owns retry-on-malformed-JSON,
      │                            owns confidence-threshold logic, evaluated by ADR-004 harness
      │
      └─► PersistenceStep        — save_meal, get_daily_summary
                                   deterministic, no LLM (once implemented)
```

### Why "Orchestrator," not "Supervisor Agent"

An LLM-based supervisor (a second model deciding which sub-agent to call) was considered and rejected for this stage — see Option B below. The routing decision itself (parse text if a meal description is present → always run the calc pipeline if profile fields are present → persist if a parse succeeded) is fully determined by which fields are present in the request. That's an `if`, not a reasoning task. Spending a model call to decide something already knowable from the request shape is the same anti-pattern ADR-002 fixed by not asking the LLM to do arithmetic.

### Component contracts

**`CalcPipeline`** (`services/calc_pipeline.py`, new — extracted from the tool functions already in `tools/bmr.py`, `tools/tdee.py`, `tools/calorie_goal.py`, unchanged)
```python
def run_calc_pipeline(profile: UserProfile) -> CalcResult:
    bmr = calculate_bmr(...)
    tdee = calculate_tdee(bmr, profile.activity_level)
    goal = calculate_calorie_goal(tdee, profile.goal, profile.goal_rate_kg_per_week)
    return CalcResult(bmr_kcal=bmr, tdee_kcal=tdee, calorie_goal_kcal=goal)
```
No LLM, no agent loop, no `MAX_STEPS`. This already exists in effect as `/api/calculate`; the change is that `/api/agent` calls this function directly instead of letting the LLM re-derive the same three-step order it's told to follow in the prompt.

**`MealParseAgent`** (`services/meal_parse_agent.py`, new — replaces the `parse_meal_text` call path inside `run_agent`)
```python
def parse_meal(meal_text: str, meal_type: str | None) -> ParsedMeal:
    # owns: prompt construction, LLM call, JSON validation,
    # retry-once-on-malformed-output (already planned in ADR-001),
    # low-confidence item flagging
```
This is the only agentic/nondeterministic component left. It is the sole subject of the ADR-004 eval harness — evals score *this* component's output against a golden dataset, not the whole pipeline, because it's the only part whose output can silently vary.

**`Orchestrator`** (`services/agent_service.py`, rewritten — same public function name `run_agent(message, llm)` so `api/routes.py`'s `/agent` endpoint signature is untouched)
```python
def run_agent(message: str, llm: BaseChatModel) -> AgentResponse:
    parsed_request = extract_request_fields(message, llm)   # one LLM call: NL → structured fields
    calc = run_calc_pipeline(parsed_request.profile) if parsed_request.profile else None
    meal = parse_meal(parsed_request.meal_text, parsed_request.meal_type) if parsed_request.meal_text else None
    if meal:
        save_meal(meal)
    return AgentResponse(response=compose_response(calc, meal), iterations_used=...)
```
`extract_request_fields` replaces the ReAct loop's field-extraction responsibility — it's still one necessary LLM call (turning free text into structured `weight_kg`, `meal_text`, etc.), but it's a single-shot structured-output call, not a multi-step tool-calling loop. This directly removes the `MAX_STEPS` iteration variance ADR-002 flagged as a latency risk ("Step count is unpredictable — some requests hit 7-8 steps").

---

## Options Considered

### Option A: Keep single ReAct agent, add evals only
Just build ADR-004's eval harness against the current `run_agent`, no structural change.

| Dimension | Assessment |
|---|---|
| Effort | Lowest |
| Fixes the "no eval" problem | ✅ |
| Fixes wasted-steps / unbounded blast radius | ❌ |
| Resume narrative | Weaker — "added evals" alone doesn't show architectural judgment |

**Rejected as insufficient, not wrong** — this is a valid interim step (and ADR-004 can land before this ADR's code does), but doesn't address the structural coupling between deterministic and nondeterministic work.

### Option B: Full multiagent — LLM-based supervisor routes to sub-agents
A supervisor LLM call decides which of {CalcAgent, MealAgent, SummaryAgent} to invoke and in what order, each sub-agent itself being a mini ReAct loop.

| Dimension | Assessment |
|---|---|
| Effort | Highest |
| Extra LLM calls | +1 (supervisor) minimum, more if sub-agents loop |
| Latency | Worse — already at ~140s per parse call (ADR-002); stacking a supervisor call on top is a regression, not an improvement |
| Justified by current requirements? | No — routing is fully determined by request shape, not by ambiguous reasoning |

**Rejected:** adds latency and an LLM call to a decision that isn't actually a decision. Revisit only if routing logic becomes genuinely ambiguous (e.g. detecting user *intent* from unstructured chat rather than a semi-structured profile+meal message).

### Option C: Orchestrator + isolated MealParseAgent, deterministic CalcPipeline ✅ (Chosen)
As described in Decision above.

| Dimension | Assessment |
|---|---|
| Effort | Medium — mostly extraction/reorganization of existing tool functions, one new single-shot LLM call for field extraction |
| Fixes no-eval problem | ✅ — isolates the one component ADR-004 needs to score |
| Fixes wasted-steps problem | ✅ — calc pipeline is 3 function calls, not up-to-8 LLM-decided steps |
| Fixes unbounded blast radius | ✅ — `save_meal` only runs on a `ParsedMeal` that passed validation, and a confidence threshold can now gate persistence in one place |
| API contract changes | None — `/api/agent`, `/api/parse-meal`, `/api/calculate` unchanged |

---

## Migration Plan (incremental, no big-bang rewrite)

1. Extract `CalcPipeline` from the three existing calc tools — pure refactor, no behavior change. Existing `/api/calculate` endpoint switches to calling it directly (already effectively does this).
2. Extract `MealParseAgent` from `tools/meal_parser.py`'s `parse_meal_text` — again largely a rename/relocation, since the LLM-calling logic already lives in one function.
3. **Land ADR-004's eval harness against `MealParseAgent` before rewriting `run_agent`** — this gives a before/after accuracy number for the orchestrator rewrite, which is the actual proof this change was worth doing.
4. Rewrite `run_agent` as the thin `Orchestrator` described above. Keep the old ReAct loop path behind a flag or in git history until the orchestrator passes the same eval suite at parity or better.
5. Remove `MAX_STEPS`-based looping once the orchestrator is confirmed at parity — it becomes dead code once nothing does open-ended multi-step tool selection.

---

## Consequences

**Becomes easier:**
- Adding a new deterministic tool (e.g. `track_water_intake`) — it's a function call in the orchestrator, not a new tool needing to be discovered correctly by an LLM's tool-selection reasoning.
- Reasoning about latency — calc pipeline is now O(3 function calls), only the meal-parse and field-extraction steps hit the LLM, both single-shot (no loop).
- Testing — `CalcPipeline` is pure-function unit-testable (already true for the underlying tools); `MealParseAgent` is the sole eval target.
- Explaining the system to an interviewer: "the nondeterministic 10% is isolated and evaluated; the rest is plain code" is a concrete, defensible architecture claim.

**Becomes harder:**
- Two LLM calls per full request (field extraction + meal parse) instead of the ReAct loop's variable 1-8 — better worst-case, but a fixed-request-shape assumption (`extract_request_fields`) that the old free-form ReAct loop didn't need. If input shapes get more varied (e.g. multi-turn chat), this may need revisiting.
- `services/agent_service.py` public function signature stays the same, but its internals are a rewrite — needs the parity check in step 4 of the migration plan, not a silent swap.

**Revisit later:**
- If a genuinely ambiguous routing decision emerges (see Option B), reconsider a lightweight supervisor call — but only with evidence the fixed-shape orchestrator can't handle it.
- If `get_daily_summary` grows real logic (e.g. trend analysis, natural-language summary generation), it may earn its own agent — right now it's a SQL aggregation with no LLM involvement, so it stays a plain step.

---

## Action Items

1. [x] Build ADR-004 eval harness first, scored against current `parse_meal_text` — done. Real baseline (`qwen2.5:3b`, 33 examples): 83.6% item precision, 92.0% item recall, 59.3% calorie MAPE, 39.6% confidence calibration (below the 50% no-signal line). This is now the number steps 4 and 7 below gate against.
2. [x] Extract `CalcPipeline` — done. New `calai_backend/services/calc_pipeline.py` (`run_calc_pipeline`); `/api/calculate` now calls it directly. Pure refactor, `/api/calculate` contract unchanged.
3. [x] Extract `MealParseAgent` — done. New `calai_backend/services/meal_parse_agent.py` (`parse_meal`); `tools/meal_parser.py` reduced to a thin wrapper. `reviewer` confirmed `/api/parse-meal` contract byte-for-byte unchanged.
4. [x] Re-run ADR-004 evals against `MealParseAgent` — done, exact parity with the committed baseline (`qwen2.5:3b`, 33 examples): 100% format validity, 83.6% item precision, 92.0% item recall, 59.3% calorie MAPE, 39.6% confidence calibration. Extraction alone caused zero drift.
5. [x] Implement `extract_request_fields` single-shot structured-output call — done, in `calai_backend/services/agent_service.py`.
6. [x] Implement `Orchestrator` rewrite of `run_agent`, behind a flag alongside the old ReAct path — done. `run_agent(message, llm)` public signature unchanged; dispatches to `_run_agent_orchestrator` or `_run_agent_react_loop` via new `USE_ORCHESTRATOR` config flag (`config.py`, defaults `true`). Old loop fully intact, reachable via `USE_ORCHESTRATOR=false`. One fix loop was needed (of the 2-loop cap) for a `compose_response` crash on non-numeric totals and missing error-translation on the new path — both closed on re-review.
7. [x] Run eval suite + a latency comparison (old ReAct loop vs. new orchestrator) — done, this is the resume artifact. Eval suite: exact parity again (same 5 figures as step 4). Latency (3 representative messages, real `qwen2.5:3b` calls, `time.perf_counter()`): react_loop totaled 402.93s vs orchestrator 179.04s across the 3 messages — **2.25x faster**. Bonus finding: on the profile-only message, the old ReAct loop's LLM-computed TDEE (3726 kcal) diverged sharply from the orchestrator's deterministic `CalcPipeline` result (2678 kcal) on identical input — direct evidence the split fixes a real correctness gap, not just a speed one. Full numbers in `evals/latency_comparison.py` and `evals/report/latest.json`.
8. [ ] Remove old ReAct loop path once orchestrator is at parity or better — **parity confirmed (steps 4 & 7), but deliberately not started** — this is a one-way deletion of currently-working code, holding for explicit user go-ahead before removing the rollback path. **Superseded by ADR-005 (2026-08-02): the ReAct loop is not deleted — it is demoted to a bounded (`REACT_FALLBACK_MAX_STEPS=3`) fallback handler wired to `Intent.UNKNOWN`, a permanent architectural role rather than a rollback path pending removal. See `archdocs/ADR-005-router-handler-registry.md`'s "Amendment to ADR-003 Action Item 8" section.**
9. [ ] Update ADR-002's status to "Superseded by ADR-003" once step 8 lands — blocked on step 8

**Note (2026-08-01):** given the confidence-calibration finding from step 1 (confidence is currently an *inverted* signal, not yet trustworthy), the "gate persistence on confidence" idea in this ADR's Decision section should not be implemented as-is until that's fixed or re-measured — flagging so step 5/6 doesn't quietly build on a broken assumption. **Confirmed as of step 6 (2026-08-02): no confidence-gating was implemented anywhere in the orchestrator rewrite, per this note.**
