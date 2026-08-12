# ADR-005: Router → Handler Registry, with Bounded ReAct as Escape Hatch

**Status:** Proposed — architecture only, no code changes yet (Phase 0 of `plans/adr005-router-handler-registry-refactor-plan.md`)
**Date:** 2026-08-02
**Deciders:** Siddhant Tomar
**Companions:** ADR-001 (system architecture), ADR-003 (multiagent split — this ADR amends Action Item 8), ADR-004 (eval harness — extended here to cover `extract_request_fields` and the real orchestrator entry point)

---

## Context

ADR-003 replaced CalAI's single ReAct tool-calling loop with a deterministic Orchestrator (`extract_request_fields` → `run_calc_pipeline` and/or `parse_meal` → `compose_response`) and measured a real win: 2.05-2.41x latency improvement and a genuine correctness bug removed (the old loop's LLM silently computed TDEE as 3726 kcal vs. the deterministic 2678 kcal on identical input). ADR-003 Action Items 2-7 are done; Action Item 8 ("delete the old ReAct loop") was deliberately left open pending evidence.

`artefacts/NOTES-orchestrator-vs-react.md`'s second-pass review re-read the shipped code against those claims and found four concrete costs of *not* fixing the orchestrator's structural gaps, each currently live in production code:

1. **All-or-nothing profile discard is a live UX regression** (`agent_service.py:95-105`, `_PROFILE_FIELD_NAMES` check on line 97). *"I'm 28, 70kg, trying to lose weight"* extracts four valid fields, silently drops all of them because a sixth is missing, and the user is asked for information they already gave — via the same generic re-ask (`compose_response`'s "Could you tell me your weight, height, age…" fallback) that a completely empty message would also trigger. No eval or test covers this because ADR-004's harness only scores meal parsing.
2. **`AgentResponse.iterations_used` (`schemas.py:26-27`) has silently changed meaning** in a contract Flutter consumes, with the same field name and type: "ReAct loop iterations, 1-8" under the old path, "pipeline steps that fired, 0-2" under the new one (`agent_service.py:226`, `sum(1 for step in (calc, meal) if step is not None)`). Nothing discriminates which meaning a given response used; a client or a future maintainer reading this field cold will misinterpret it as a loop count.
3. **The TDEE-divergence bug that motivated ADR-003 is unguarded.** It was found by accident in an n=1 latency script (`artefacts/adr003-latency-comparison.json`) and has zero permanent regression coverage. The single most persuasive evidence for ADR-003's rewrite currently lives only in a JSON artefact and a paragraph — nothing in `calai_backend/tests/` would catch a future regression of this exact bug.
4. **The eval-parity claim proves less than it sounds.** `evals/run_eval.py` feeds golden `meal_text` straight into `parse_meal_text`, bypassing `extract_request_fields` entirely. Production's actual input to `parse_meal` is now LLM-reworded text from `extract_request_fields`, not the user's original words — so "parity" proves the *unchanged component* didn't change, and says nothing about whether end-to-end meal-logging accuracy held, improved, or regressed after ADR-003 shipped.

There is also a structural gap ADR-003 explicitly accepted as a v1 tradeoff and flagged for revisiting: **an out-of-scope message has no "I don't know what to do with this" path.** It's silently forced through `extract_request_fields`, producing a plausible-looking but potentially wrong structured result — the old ReAct loop's failure mode (hit `MAX_STEPS`, error loudly) was slower but at least visible; the orchestrator's failure mode is fast and silent.

This ADR's cost of inaction, concretely: every one of the four findings above is currently unfixed and unguarded in the code the API actually serves, and the pattern that would fix all four ("router → typed capability handlers, with a bounded agent as escape hatch," per the retrospective) was scoped there but never formalized into typed contracts an engineer could implement against.

---

## Non-Goals

- This does **not** reintroduce an LLM supervisor, a message bus, an async job queue, or a separate standalone intent-classifier LLM call. ADR-003's Option B rejection (routing isn't ambiguous enough to justify a model call) still holds. The `Intent` field added here is populated inside `extract_request_fields`'s **existing** JSON-mode call — zero new LLM round-trips, zero new latency.
- This does not change `/api/agent`, `/api/parse-meal`, or `/api/calculate`'s request shapes. `AgentResponse` gains a field (see the `iterations_used` resolution below); nothing existing is removed.
- This does not implement `save_meal` / `get_daily_summary` persistence — still out of scope per ADR-001/ADR-003.
- This does not fix confidence calibration (39.6%, below the 50% no-signal line) — still a known, unaddressed limitation, not gated on anything here.
- This does not delete `_run_agent_react_loop`. It formally amends ADR-003 Action Item 8 from "delete" to "demote to a capped fallback" — see the amendment section below.

---

## Decision

Replace the orchestrator's fixed two-branch if/else with **Intent classification (same LLM call) → handler registry dispatch → typed `StepResult` → bounded ReAct fallback for the unclassified case.** Seven contracts, all typed below, no prose-only descriptions.

### 1. `Intent` enum

`calai_backend/schemas.py`, new class placed near `ParsedRequest`:

```python
class Intent(str, Enum):
    LOG_MEAL = "log_meal"
    SET_PROFILE = "set_profile"
    UNKNOWN = "unknown"
```

**Routing-model decision (resolves REQ-01's open tradeoff — read this before implementing):** `Intent` is **not** a second routing mechanism competing with today's presence-based dispatch (`if parsed_request.profile: ...`, `if parsed_request.meal_text: ...`). ADR-003's core bet — that which known capability to invoke is fully determined by which fields are present in the extracted request, not by a classification decision — is unchanged and still correct; the eval-parity result (identical meal-parsing scores before/after ADR-003) is indirect confirmation this bet held. A message containing both a complete profile and meal text still runs **both** handlers, exactly as today — `Intent` does not collapse that into a forced single choice, and a handler must not special-case on `Intent` to decide *whether* it runs; presence of its own required fields on `ParsedRequest` remains the only gate.

`Intent` exists for exactly one purpose the presence checks cannot express: **naming the case where neither shape matches.** `UNKNOWN` fires when the message produces neither a usable profile-field set nor usable `meal_text` — i.e., it is the explicit encoding of "no known handler applies," not a replacement for the checks that decide which known handler(s) apply. Concretely: `Intent` is read by `_run_agent_orchestrator` only to decide *whether to invoke the ReAct fallback* (`Intent.UNKNOWN` → fallback); it is never read by `handle_log_meal` or `handle_set_profile` to decide whether *they* run. `ai-engineer` must not build a second if/else keyed on `Intent` alongside the existing presence checks — there is exactly one router in this system, and it is presence-based, with `Intent.UNKNOWN` as the signal that presence-based routing found nothing to do.

### 2. Extended extraction schema

`ParsedRequest.intent: Intent` — new required field on the existing model (`calai_backend/schemas.py`), populated by `extract_request_fields` (`agent_service.py:57-117`) in the **same JSON-mode call** that already extracts profile fields and `meal_text`. No second LLM round-trip. `EXTRACTION_PROMPT`'s JSON schema gains one field:

```json
{
  "...": "existing fields unchanged",
  "intent": "log_meal" | "set_profile" | "unknown"
}
```

`UNKNOWN` is returned by the model (or defaulted by `extract_request_fields` if the model omits it or returns an unrecognized value — do not raise `ValueError` for an unrecognized intent string; coerce to `UNKNOWN` and log a WARNING, since `Intent` is meant to be a soft signal for the fallback path, not a hard validation gate that turns a parseable-but-ambiguous message into an HTTP error) when the message matches neither the profile shape (per the existing `_PROFILE_FIELD_NAMES` presence check) nor produces usable `meal_text`.

### 3. `Handler` protocol

New module `calai_backend/services/handlers/base.py`:

```python
@dataclass(frozen=True)
class HandlerContext:
    llm: BaseChatModel
    correlation_id: str

Handler = Callable[[ParsedRequest, HandlerContext], StepResult]
```

Every handler (registry values, `HANDLERS` below) matches this exact signature — no ad hoc per-handler extra parameters. Anything handler-specific goes through `ParsedRequest` fields or a documented, versioned `HandlerContext` extension (adding a field to `HandlerContext` is allowed; adding a positional/keyword parameter to `Handler` itself is not, since it would break registry-uniform dispatch).

### 4. `StepResult` sum type

New module `calai_backend/services/step_result.py`:

```python
@dataclass(frozen=True)
class StepOk:
    kind: Literal["ok"] = "ok"
    data: CalcResult | MealParseResult  # existing result shapes, imported not redefined

@dataclass(frozen=True)
class NeedsMoreInfo:
    kind: Literal["needs_more_info"] = "needs_more_info"
    missing: list[str]

StepResult = StepOk | NeedsMoreInfo
```

Replaces the silent-discard branch at `agent_service.py:95-105` (finding #1). Partial profile input returns `NeedsMoreInfo(missing=[...])` naming exactly which of the six `_PROFILE_FIELD_NAMES` fields (excluding `goal_rate_kg_per_week`, which already has a schema default) are absent — never a bare `None` that throws away fields the model did extract.

### 5. `llm_call` wrapper

New module `calai_backend/services/llm_call.py`:

```python
class LLMCallResult(BaseModel):
    output: BaseModel
    raw_response: str
    latency_ms: float
    retry_count: int

def llm_call(name: str, prompt: str, schema: type[BaseModel], llm: BaseChatModel) -> LLMCallResult:
    ...
```

**Retry policy:** exactly **one** retry on malformed JSON or schema-validation failure, then raise `ValueError` — this matches `extract_request_fields`'s and `parse_meal`'s existing failure contract (both currently raise `ValueError` on the *first* failure with zero retries; adding one retry before raising is a pure improvement, not a contract change, since callers already handle `ValueError` → HTTP 422 translation in `_run_agent_orchestrator`, `agent_service.py:212-214`). No exponential backoff, no second retry — one retry is the entire policy, chosen because a malformed JSON-mode response from a 3B local model is usually a one-off decoding artifact, not a systematic failure a second retry would fix; a persistent failure should surface as an error, not be masked by more attempts. `llm_call` emits exactly one `TraceRecord` per invocation (contract 6, below), including when the retry path fires (`retry_count=1`).

`llm_call` is the **single failure mode** for every LLM surface in this system: malformed JSON or schema-validation failure after one retry → `ValueError`, propagated to callers unchanged. `extract_request_fields` and `meal_parse_agent.py::parse_meal` are migrated to call `llm_call` instead of hand-rolling `json.loads` + validation; their observable behavior (what exception fires, when) does not change, only where the JSON-parse-and-validate logic lives.

### 6. Trace record schema + logging contract

`calai_backend/logging_config.py` (new):
- `get_logger(name: str) -> logging.Logger` — every module (`agent_service.py`, `calc_pipeline.py`, `meal_parse_agent.py`, every file under `services/handlers/`) gets one `logger = get_logger(__name__)`.
- Correlation-id mechanism: `contextvars.ContextVar[str]("correlation_id")`, plus `bind_correlation_id(cid: str)` — a context manager called exactly once per request, at the top of `_run_agent_orchestrator`, generating a UUID4 if none was supplied. Every `logger.debug`/`.warning` call and every `TraceRecord` read the same context var, so one correlation id ties together every log line and trace record for a single request without threading it through every function's parameter list explicitly (`HandlerContext.correlation_id` is still passed explicitly to handlers per contract 3, for handlers that need to reference it directly, e.g. when constructing a `TraceRecord`).

`calai_backend/services/trace.py` (new):

```python
class TraceRecord(BaseModel):
    call_name: str
    correlation_id: str
    prompt: str
    raw_response: str
    parsed_output: dict
    latency_ms: float
    retry_count: int
    timestamp: datetime
    outcome: Literal["ok", "needs_more_info", "fallback", "error"]
```

Persisted append-only, one file per day: `calai_backend/logs/traces/{date}.jsonl` (mirrors the `evals/dataset/*.jsonl` convention already in this repo — same JSONL family, directly convertible to eval data later, per the retrospective's "free eval dataset" point). `llm_call` emits exactly one `TraceRecord` per invocation.

**Logging field vocabulary (shared, not diverging):** DEBUG/WARNING log lines use exactly these structured field names — `intent`, `handler`, `step`, `latency_ms`, `outcome`, `correlation_id` — the same names as `TraceRecord`'s fields (`outcome`, `latency_ms`, `correlation_id` are literal `TraceRecord` fields; `intent` and `handler` are the request's `Intent` value and the dispatched handler's name, logged alongside every trace-adjacent event even though `TraceRecord` itself doesn't carry them as top-level fields — they belong on the orchestrator/handler-dispatch log lines that wrap each `llm_call`). This is explicitly **one vocabulary**, not two schemas that can drift: a `logger.debug(...)` call at a decision point and the `TraceRecord` for the `llm_call` it wraps describe the same event using the same field names, so a developer can grep logs and cross-reference a trace file without translating terminology.

**DEBUG-level logging (every decision point):**
- Which `Intent` was classified, and the raw extracted fields it was classified from (not just the enum value) — logged in `extract_request_fields`.
- Which handler the registry dispatched to for a given `Intent`.
- Every `StepResult` returned, including the full `missing=[...]` list on `NeedsMoreInfo`.
- Every `llm_call` invocation: prompt name, latency, retry count, validation outcome.

**WARNING-level logging (suspicious but not fatal):**
- A computed TDEE outside a sane physiological range (e.g. <500 or >6000 kcal/day) — this is the exact signal that would have caught the ADR-003 TDEE divergence immediately instead of by accident.
- `Intent.UNKNOWN` firing the ReAct fallback (`outcome="fallback"`).
- A retry firing inside `llm_call` (`retry_count=1`).
- Confidence field present but not gated on — logged once per meal-parse call as "confidence field present but not gated on — known miscalibration, see ADR-004/ADR-005 Known Limitations," replacing a bare code comment as the only record of that decision.

This is a **seventh required contract**, the same bar as the six above — not an implicit side effect of the trace-record file layout. Every `ai-engineer` sub-stage implementing REQ-01 through REQ-08 ships its logging in the same change as its behavior change; `reviewer` treats missing DEBUG/WARNING coverage at a new decision point as a bug-bucket finding, not a simplification nicety.

### 7. Handler registry

Package `calai_backend/services/handlers/` (new), one file per handler:
- `calai_backend/services/handlers/log_meal.py` → `handle_log_meal(request: ParsedRequest, ctx: HandlerContext) -> StepResult`
- `calai_backend/services/handlers/set_profile.py` → `handle_set_profile(request: ParsedRequest, ctx: HandlerContext) -> StepResult`

Registry, `calai_backend/services/handler_registry.py`:

```python
HANDLERS: dict[Intent, Handler] = {
    Intent.LOG_MEAL: handle_log_meal,
    Intent.SET_PROFILE: handle_set_profile,
}
```

`Intent.UNKNOWN` is deliberately **not** a `HANDLERS` key — it is routed to the fallback handler (contract 8) directly by `_run_agent_orchestrator`, not through the registry, so `HANDLERS` only ever contains fully-typed, non-fallback capability handlers. **Registration convention:** a new request shape = a new file under `services/handlers/` + one new entry in `HANDLERS` — `_run_agent_orchestrator` itself is never touched to add a capability. `_run_agent_orchestrator` (`agent_service.py:166-232`) replaces its current if/else with `HANDLERS.get(parsed_request.intent)` dispatch for the known-shape presence checks (contract 1's routing decision still governs *which* fields/handlers actually run per request — the registry supplies *how* a given handler is looked up, not a new decision of *whether* it runs).

### `iterations_used` resolution (REQ-07)

**Decision: alias, no break.** Add a new, explicitly-named field:

```python
class AgentResponse(BaseModel):
    response: str
    pipeline_steps_run: int
    """Count of {calc, meal} handler steps that executed on the orchestrator
    path — 0, 1, or 2. Orchestrator path only; see iterations_used for the
    legacy ReAct-path meaning."""
    iterations_used: int
    """Deprecated — use pipeline_steps_run. Meaning differs between the
    legacy ReAct path (loop iteration count, 1-8, USE_ORCHESTRATOR=false)
    and the orchestrator path, where it is set equal to pipeline_steps_run
    for backward compatibility only. Do not add new logic depending on this
    field; it exists solely so existing Flutter clients reading
    iterations_used do not silently misinterpret a value whose meaning
    changed without their knowledge."""
```

On the orchestrator path, `iterations_used` is set equal to `pipeline_steps_run` (not removed, not further repurposed) — Flutter clients that read `iterations_used` today get the same numeric value they get today (0/1/2, per ADR-003's existing behavior); nothing about their current runtime behavior changes. `pipeline_steps_run` is the new, correctly-named field for anything built after this ADR. On the ReAct fallback path (contract 8), `iterations_used` retains its original 1-3 meaning (loop iteration count, now capped at `REACT_FALLBACK_MAX_STEPS`); `pipeline_steps_run` is not meaningful there and should be set to `0` with a comment noting the fallback path doesn't run pipeline steps.

**Why the alias is sufficient for this refactor's scope, not an escalation item:** removing `iterations_used` entirely would be a breaking Flutter contract change not requested by this ADR's scope, which CLAUDE.md requires escalating rather than silently deciding. The alias approach avoids that break outright — no Flutter code changes required, no behavior change for any existing consumer of `iterations_used`, and the new field is purely additive. The alias does not "kick the can" on an unresolved ambiguity: the docstring is the resolution — `iterations_used`'s meaning is now pinned (mirrors `pipeline_steps_run` on the orchestrator path, retains its original meaning on the fallback path) rather than drifting further. This is judged sufficient and is **not** escalated to the user. A future ADR may propose full removal once Flutter has migrated to `pipeline_steps_run` and a deprecation window has passed — that is a separate, explicit decision, not a default outcome of this ADR.

### 8. ReAct-as-fallback contract

- `calai_backend/config.py`: new constant `REACT_FALLBACK_MAX_STEPS = 3`.
- `calai_backend/services/handlers/react_fallback.py` (new): `handle_react_fallback(request: ParsedRequest, ctx: HandlerContext) -> StepResult` — wraps the existing `_run_agent_react_loop` (`agent_service.py:254-339`), passing it a step cap of `REACT_FALLBACK_MAX_STEPS` (not `MAX_STEPS=8`, which remains the cap for any future direct/manual invocation of the full ReAct loop outside this fallback role, if one is ever added), and converts its `AgentResponse` return into `StepOk`/`NeedsMoreInfo`.
- `_run_agent_orchestrator` routes `Intent.UNKNOWN` to `handle_react_fallback` **explicitly**, not via `HANDLERS` (contract 7) — the registry contains only fully-typed, non-fallback handlers by design.
- Logs at WARNING on every fallback trigger, `outcome="fallback"`, per contract 6.

**`_run_agent_react_loop` itself is untouched except being wrapped — never deleted.** This is the formal amendment to ADR-003 Action Item 8 (see below).

---

## Amendment to ADR-003 Action Item 8

ADR-003 Action Item 8 read: *"Remove old ReAct loop path once orchestrator is at parity or better — parity confirmed (steps 4 & 7), but deliberately not started — this is a one-way deletion of currently-working code, holding for explicit user go-ahead before removing the rollback path."*

**This ADR supersedes that action item.** The ReAct loop is not deleted. It is demoted to a bounded (`REACT_FALLBACK_MAX_STEPS = 3`) fallback handler, wired to fire specifically and only on `Intent.UNKNOWN`, logged at WARNING every time it triggers. This converts the loop from "working code nobody feels safe deleting" into "the orchestrator's graceful-degradation path for the exact class of input the fixed-shape router structurally cannot classify" — a permanent, intentional architectural role, not a rollback mechanism awaiting removal. ADR-003 Action Item 8 should be marked **superseded by ADR-005** rather than completed or left open; `USE_ORCHESTRATOR=false` (full, uncapped ReAct loop, `MAX_STEPS=8`) remains available for manual rollback/debugging independent of the new capped fallback role, and is unaffected by this change.

---

## Known Limitations

Two items, each with an owner and a target closure phase, tracked here rather than only in a code comment (per the cross-cutting Logging requirement's principle that a known issue must be visible at runtime and in the design record, not just at read-time):

1. **TDEE divergence (ReAct 3726 kcal vs. orchestrator 2678 kcal on identical input).** Found by accident in an n=1 latency script (`artefacts/adr003-latency-comparison.json`); currently has zero permanent regression coverage. **Status: OPEN.** Owner: `tester`. Closes in Phase 1 sub-stage 1a — `calai_backend/tests/test_tdee_divergence_regression.py`, asserting the deterministic `run_calc_pipeline` value on the exact input that produced the divergence. To be updated to "Closed — see `calai_backend/tests/test_tdee_divergence_regression.py`" once that test lands and passes.
2. **Eval-parity gap (`evals/run_eval.py` bypasses `extract_request_fields`).** Current eval scores measure whether `parse_meal_text`/`parse_meal` changed, not whether end-to-end production meal-logging accuracy held after ADR-003, because production's input to `parse_meal` is now LLM-reworded text from `extract_request_fields`, not the user's original wording. **Status: OPEN.** Owner: `tester`. Closes in Phase 2 sub-stage 2a — `evals/run_eval.py` updated to exercise the real orchestrator entry point (not `parse_meal_text` directly) for at least a subset of `evals/dataset/*.jsonl`. To be updated to "Closed — see `evals/run_eval.py`'s orchestrator-path exercise + `evals/report/latest.json`'s updated run" once that lands.

Confidence-calibration (39.6%, inverted signal) is explicitly **not** listed here as an item this ADR tracks toward closure — it remains a known, separately-scoped limitation per ADR-003's existing note and this ADR's Non-Goals.

---

## Options Considered

### Option A: Fix the four findings in place, no new abstractions
Patch `_PROFILE_FIELD_NAMES`'s all-or-nothing check to return partial results, rename `iterations_used`, add a TDEE regression test, and fix the eval harness's entry point — all as targeted diffs inside `agent_service.py`, without introducing `Intent`, `StepResult`, `Handler`, or a registry.

| Dimension | Assessment |
|---|---|
| Effort | Lowest — four independent small diffs |
| Fixes findings #1-#4 | Partially — #2, #3, #4 yes; #1 only if the discard logic is reworked to a shape that names *what's missing*, which is most of `StepResult`'s value anyway |
| Fixes the "no `UNKNOWN` path" gap | No — there's still no explicit signal for "message matched neither shape," so out-of-scope input keeps silently forcing a best-effort extraction |
| Extensibility | Unchanged — adding a third capability (e.g. `daily_summary`) still means a new `if` branch inside `_run_agent_orchestrator`, the exact "surgery on the orchestrator" cost the retrospective flags as the ReAct loop's one fair advantage |
| Resume/narrative value | Weaker — "patched four bugs" is a bug-fix changelog, not an architecture decision; doesn't demonstrate the router/handler/fallback pattern as a reusable, generalizable design |

**Rejected as insufficient, not wrong.** This closes the four findings but leaves the structural gap (no `UNKNOWN` path, if/else that grows with every new capability) exactly where ADR-003's own retrospective identified it as the next real risk. Given that the retrospective already scoped the fuller pattern and estimated it as low-incremental-cost (the enum rides the existing extraction call, at zero added latency, per the retrospective's own "flat latency" prediction), patching in place trades a small effort savings now for the same structural cost resurfacing at the next capability addition.

### Option B: Full LLM supervisor + sub-agent routing
A supervisor LLM call classifies the message and decides which sub-agent(s) to invoke, each sub-agent itself a small ReAct loop.

| Dimension | Assessment |
|---|---|
| Effort | Highest |
| Extra LLM calls | +1 minimum (supervisor), more if sub-agents loop |
| Latency | Regression — adds a full LLM round-trip (~30s on this hardware/model, per the retrospective's per-call latency breakdown) to every request, for a routing decision that isn't actually ambiguous |
| Justified by current requirements? | No — same reasoning as ADR-003's rejection of its own Option B; two known request shapes plus an explicit unknown case doesn't need a reasoning model to route |

**Rejected**, consistent with ADR-003's prior rejection of the same shape of option. Revisit only if routing itself becomes genuinely ambiguous — not the case here; `Intent` is read from the same single extraction call already being made, at zero added cost.

### Option C: Router → typed capability handlers, with bounded ReAct as escape hatch ✅ (Chosen)
As described in Decision above — `Intent` merged into the existing `extract_request_fields` call, presence-based routing retained for known shapes, `HANDLERS` registry for extensibility, `StepResult` for partial-input slot-filling, bounded (`REACT_FALLBACK_MAX_STEPS=3`) ReAct fallback for `UNKNOWN`.

| Dimension | Assessment |
|---|---|
| Effort | Medium — no new LLM calls, mostly typed contracts around existing logic plus one new fallback wrapper |
| Fixes findings #1-#4 | Yes, all four, each with a named owning phase and a regression test |
| Fixes the "no `UNKNOWN` path" gap | Yes — `Intent.UNKNOWN` is an explicit, non-default enum member with a defined fallback behavior, not a silent best-effort extraction |
| Extensibility | New capability = new handler file + one registry line, not a new orchestrator branch — directly answers the retrospective's "fairest criticism" of the pure-orchestrator design |
| Latency | Flat — zero new LLM calls; `Intent` rides the existing `extract_request_fields` JSON-mode call |
| Resume/narrative value | Strongest — demonstrates recognizing and closing a structural gap in a design already shipped, with typed contracts and regression coverage, not just a bug-fix pass |

---

## Consequences

**Becomes easier:**
- Adding a new capability handler (e.g. a future `daily_summary` intent) — one new file under `services/handlers/` and one `HANDLERS` entry, never a change to `_run_agent_orchestrator` itself.
- Diagnosing a slot-filling failure — `NeedsMoreInfo(missing=[...])` is logged at DEBUG with the full list, not silently discarded.
- Diagnosing the TDEE-divergence class of bug in general — WARNING-level physiological-range checks and `TraceRecord`s turn "found by accident in an n=1 script" into "would show up in `calai_backend/logs/traces/{date}.jsonl` and a WARNING log line on the next occurrence."
- Building future eval datasets for any LLM surface — every `llm_call` invocation already produces a `TraceRecord` in the same JSONL family as `evals/dataset/*.jsonl`.

**Becomes harder:**
- Slightly more indirection to trace a request end-to-end (`_run_agent_orchestrator` → registry lookup → handler → `StepResult`) versus the previous two-branch if/else — mitigated by the correlation-id-threaded logging contract (contract 6), which is specifically designed so a `correlation_id` grep reconstructs the full path without needing to read the dispatch code.
- Two schemas (`Intent`'s "known shape" semantics vs. presence-based routing's "which fields exist" semantics) coexist in one function; `ai-engineer` must not conflate them into a second competing router, per contract 1's explicit resolution — this ADR states the boundary explicitly specifically to prevent that confusion, but it is a real ongoing discipline requirement, not a one-time decision.

**Revisit later:**
- Full removal of `iterations_used` once Flutter has migrated to `pipeline_steps_run` and a deprecation window has passed — a separate, explicit ADR/decision, not an automatic follow-on to this one.
- If `Intent.UNKNOWN` fires at a rate high enough to suggest the two known shapes are no longer sufficient coverage of real usage (measurable via `outcome="fallback"` trace records once contract 6 is live), that's evidence for adding a third known `Intent` + handler, not for expanding the fallback's step cap.

---

## Action Items

1. [ ] `Intent(str, Enum)` added to `calai_backend/schemas.py` with exactly `LOG_MEAL`, `SET_PROFILE`, `UNKNOWN` — verify: `python -c "from calai_backend.schemas import Intent; assert {i.value for i in Intent} == {'log_meal','set_profile','unknown'}"`.
2. [ ] `ParsedRequest.intent: Intent` is a required field, populated by `extract_request_fields` inside its existing single JSON-mode call — verify: no new `llm.invoke(...)` call added to `extract_request_fields` (`git diff` shows exactly one `json_llm.invoke` call site, matching the pre-change function).
3. [ ] `calai_backend/services/step_result.py` exists with `StepOk`, `NeedsMoreInfo`, and `StepResult = StepOk | NeedsMoreInfo` matching contract 4's field names exactly (`kind`, `data`, `missing`).
4. [ ] `calai_backend/services/handlers/base.py` exists with `HandlerContext` (`llm`, `correlation_id`) and `Handler = Callable[[ParsedRequest, HandlerContext], StepResult]`.
5. [ ] `calai_backend/services/llm_call.py` exists with `llm_call(name, prompt, schema, llm) -> LLMCallResult`; `extract_request_fields` and `meal_parse_agent.py::parse_meal` both call it instead of hand-rolled `json.loads` — verify: `grep -n "json.loads" calai_backend/services/agent_service.py calai_backend/services/meal_parse_agent.py` returns no matches outside `llm_call.py` itself.
6. [ ] Retry policy is exactly one retry then raise — verify via `tester`'s pytest case forcing two consecutive malformed responses and asserting `ValueError` is raised on the second, with `retry_count=1` on the emitted `TraceRecord`.
7. [ ] `calai_backend/logging_config.py` exists with `get_logger`, `bind_correlation_id`; `calai_backend/services/trace.py` exists with `TraceRecord` matching contract 6's fields exactly; `calai_backend/logs/traces/{date}.jsonl` is written to on at least one `llm_call` invocation — verify: run one `/api/agent` request locally, confirm a `.jsonl` file appears under `calai_backend/logs/traces/` with a parseable `TraceRecord`-shaped line.
8. [ ] DEBUG-level logs fire at all four listed decision points (intent classification, handler dispatch, every `StepResult`, every `llm_call`) using the shared field vocabulary (`intent`, `handler`, `step`, `latency_ms`, `outcome`, `correlation_id`) — verify: `tester`'s per-phase log-emission assertions (per the phased plan's Logging requirement) pass, and `reviewer` confirms no new decision point ships without a corresponding DEBUG line.
9. [ ] WARNING-level logs fire on: out-of-range TDEE, `UNKNOWN`-triggered fallback (`outcome="fallback"`), any `llm_call` retry, and confidence-present-not-gated — verify: `tester`'s WARNING-level pytest assertions for each of the four triggers.
10. [ ] `calai_backend/services/handlers/log_meal.py::handle_log_meal` and `.../set_profile.py::handle_set_profile` exist matching the `Handler` signature exactly; `calai_backend/services/handler_registry.py::HANDLERS` contains exactly these two keys (`Intent.UNKNOWN` absent) — verify: `python -c "from calai_backend.services.handler_registry import HANDLERS; from calai_backend.schemas import Intent; assert set(HANDLERS) == {Intent.LOG_MEAL, Intent.SET_PROFILE}"`.
11. [ ] `_run_agent_orchestrator` dispatches via `HANDLERS.get(...)` for known shapes and routes `Intent.UNKNOWN` to `handle_react_fallback` directly (not via `HANDLERS`) — verify: `reviewer` confirms no remaining hardcoded if/else branch for `LOG_MEAL`/`SET_PROFILE` dispatch in `agent_service.py`.
12. [ ] `AgentResponse.pipeline_steps_run: int` added; `AgentResponse.iterations_used` retained with the exact deprecation docstring from contract "`iterations_used` resolution" above, and set equal to `pipeline_steps_run` on the orchestrator path — verify: `tester`'s pytest asserting both fields carry the same value (0/1/2) on the orchestrator path for a representative request, and that no existing Flutter-facing response shape lost a field (`git diff calai_backend/schemas.py` shows only additions to `AgentResponse`, no removed field).
13. [ ] `REACT_FALLBACK_MAX_STEPS = 3` added to `calai_backend/config.py`; `calai_backend/services/handlers/react_fallback.py::handle_react_fallback` wraps `_run_agent_react_loop` with this cap and converts its result to `StepOk`/`NeedsMoreInfo` — verify: `tester`'s pytest forcing `Intent.UNKNOWN` classification, asserting the fallback fires, respects the 3-step cap (not `MAX_STEPS=8`), and logs at WARNING with `outcome="fallback"`.
14. [ ] `_run_agent_react_loop` itself is byte-for-byte unmodified except for being wrapped/called from `handle_react_fallback` — verify: `git diff` on the function body of `_run_agent_react_loop` (lines currently 254-339) shows no changes.
15. [ ] ADR-003 Action Item 8 updated to read "Superseded by ADR-005 — demoted to capped fallback, never deleted" with a link to this ADR.
16. [ ] Known Limitations item 1 (TDEE divergence) closed — `calai_backend/tests/test_tdee_divergence_regression.py` exists, passes, and asserts the deterministic `run_calc_pipeline` output on the exact profile input that produced the ADR-003 divergence.
17. [ ] Known Limitations item 2 (eval-parity gap) closed — `evals/run_eval.py` exercises the real orchestrator entry point (not `parse_meal_text` directly) for at least a subset of `evals/dataset/*.jsonl`, and `evals/report/latest.json` is regenerated showing no regression on the 4 non-calibration tracked metrics (100% format validity / 83.6% precision / 92.0% recall / 59.3% MAPE baseline).
18. [ ] Full suite gate: `pytest calai_backend/tests/ -v` passes including all new tests from items 6-17; `python evals/run_eval.py` regenerates `evals/report/latest.json` with no regression on format validity, item precision, item recall, or calorie MAPE versus the committed baseline (calibration explicitly excluded, per Non-Goals).
