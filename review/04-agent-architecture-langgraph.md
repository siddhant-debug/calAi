# 04 — The app's agent: corrected scope, and where LangGraph actually earns its place

> **Revised 2026-09-13** after a scope challenge that holds up: *profile is captured once
> during setup and is mandatory, not negotiated in conversation.* The first version of this
> file designed slot-filling and `interrupt()` for missing profile fields. That was wrong for
> this product. The original design is preserved in §8 as the "chat-mode" variant, for if/when
> a conversational surface is actually built.
>
> ⚠️ **`archdocs/frontendidea.md` is NOT final** (confirmed by the user, 2026-09-13). §0.1
> separates what is decided from what this file merely assumed from that doc — read it before
> relying on anything here.

## 0. The correction, and what it collapses

**Decided (your call, stated directly):** the user profile is **mandatory and captured during
a setup step**, not extracted from free text. CalAI is a food/calorie tracker — the profile is
a precondition for computing a calorie goal at all, so there is no state in which a user is
logging food without one.

That alone is enough to collapse the slot-filling design, because it removes the only case
`NeedsMoreInfo` existed to serve. Consequences:

| Thing ADR-005 builds | Still needed for v1? | Why |
|---|---|---|
| `NeedsMoreInfo` / slot-filling for profile | ❌ No | The form cannot submit a partial profile. Validation happens in the UI and again in Pydantic. |
| `interrupt()` + checkpointer for multi-turn | ❌ No | There is no multi-turn interaction in the product. Two screens, two structured calls. |
| `extract_request_fields` (LLM call #1) | ❌ Not on any shipped path | It exists to pull profile/meal out of free prose. Onboarding sends typed JSON; meal logging sends `meal_text` directly. |
| `Intent` enum + router + `HANDLERS` registry | ❌ Not for v1 | Nothing to route: the *endpoint* already determines the operation. `/api/calculate` = profile math, `/api/parse-meal` = meal parsing. URL routing is the router. |
| Bounded ReAct fallback | ❌ Not for v1 | Nothing generic to fall back from. |
| `parse_meal` (LLM call #2) | ✅ **Yes** | The only nondeterministic component, and the only one with an eval gate. |
| `calc` pipeline (pure Python) | ✅ Yes | Already deterministic, already unit-tested. |
| Logging/trace contract, typed errors | ✅ Yes | Keep in full — these are independent of the graph question. |

### 0.1 What's decided vs. what this file assumed from a non-final doc

| Claim | Status | If it changes |
|---|---|---|
| Profile is mandatory, captured at setup, not from free text | ✅ **Decided by you** | — |
| ⇒ no slot-filling, no `interrupt()`, no checkpointer for v1 | ✅ Follows from the above | — |
| ⇒ `calc` stays deterministic, no LLM | ✅ Independent (ADR-003 measured this) | — |
| Meal logging sends `meal_text` from a text input, structured, one call | 🟡 Assumed — likely but tied to UI design | if meals arrive as free-form chat, extraction returns |
| No conversational surface in v1 | 🟡 **Open** — depends on UI direction | §8 Trigger B applies; the original design becomes right |
| Persistence is client-side SharedPreferences (`user_profile`, `calorie_goal`, `meals_YYYY-MM-DD`) | 🔴 **Was justified only by `frontendidea.md`** — now re-opened | if server-side, backend Steps 5–6 (`save_meal`, `get_daily_summary`) + a real schema come back into scope, and `scratch/blockers.md` #A3 stops being "resolved" |
| Onboarding is a 4-step forward-only `PageView` with a `go_router` redirect | 🔴 Non-final UI detail | shape of the setup flow changes, but *not* the "profile is mandatory" conclusion |

**The one that matters most is persistence.** I previously marked it "already resolved — no
backend DB work needed" in `scratch/blockers.md`. That was on the strength of
`frontendidea.md`, so it needs re-deciding. It's the difference between a device-local app
and one with history/sync — a product decision, not a technical one.

📘 **Learn this — "the endpoint is the router."** ADR-005's premise is that one free-text
entry point needs to decide what the user wants. But a form-driven app has already made that
decision on the client, at the point where the user tapped a specific button. Routing logic
inside the server is then a second, weaker copy of a decision that was already made with
perfect information. Recognising *where a decision is already determined* is most of what
keeps an architecture small.

**The blunt version:** ADR-005 is well-designed infrastructure for a product shape CalAI
doesn't have. Its four *bug fixes* are real and should survive (see §7); its *routing
architecture* should be deferred until a chat surface exists, not built now.

## 1. What v1 actually needs

Two independent paths. Neither is a graph today:

```
ONBOARDING (once)                        MEAL LOGGING (many times/day)
  4-step form                              text input
      │ typed JSON                             │ {meal_text, meal_type}
      ▼                                        ▼
  POST /api/calculate                      POST /api/parse-meal
      │ no LLM                                 │ 1 LLM call, structured output
      ▼                                        ▼
  bmr → tdee → goal   (pure Python)        items[] + total_kcal   (eval-gated)
      │                                        │
      ▼                                        ▼
  stored client-side                       appended client-side
```

Judged purely on "what does v1 need", LangGraph is over-built for this — an LCEL chain plus
the `llm_call` validate-repair wrapper does it.

**But that is the wrong yardstick for this project.** CalAI's stated purpose is comparing
architecture patterns with measured results: ADR-002 (ReAct) → ADR-003 (Orchestrator, measured
2.05–2.41× faster, found a real arithmetic bug) → ADR-006 (provider swap, re-measured) is
already a deliberate experiment series, and the plan is to keep adding arms. Under *that* goal,
LangGraph is a **third measured arm**, not premature complexity — and the point of running it
on a simple pipeline is that the comparison is clean.

So the recommendation is: **run LangGraph as a flagged experiment arm with numbers, exactly
like ADR-003 did** — not "adopt it because it's the modern choice", and not "skip it because v1
is simple". §2 is what to harden regardless of arm; §2.5 is how to run the comparison fairly.

## 2. v1 recommendation (no LangGraph, no router)

1. **Keep `/api/calculate` exactly as is.** Deterministic, fast, tested. Nothing to do.
2. **Harden `/api/parse-meal`** — this is where all remaining risk lives:
   - `llm.with_structured_output(MealParseResponse)` with enums for `unit` and `confidence`
     (narrow schemas are what make small models reliable).
   - Validate → **repair once with the validator's error text fed back** → typed failure.
     Your `llm_call` already does one-retry-then-raise; the improvement is feeding the
     `ValidationError` message into the retry, which is what actually helps a small model.
   - Few-shot 2–3 examples pulled from `evals/dataset/*.jsonl`, versioned with the prompt.
   - `temperature=0`; log `model_id` + `prompt_version` on every call.
3. **Add the typed error taxonomy + single error envelope** (§5) — this is the blocker from
   `scratch/blockers.md` #1b and it's independent of any framework choice.
4. **Solve the 9–40 s wait with streaming** (§6) — `StreamingResponse` over a plain async
   generator is enough; you do not need `astream_events` for a single-call pipeline.
5. **Demote `/api/agent`**: mark it experimental in the OpenAPI description, exclude it from
   the frontend contract doc, and do not extend it. Decide later (§8) whether it becomes a
   real chat surface or gets deleted.

That's it. Steps 2–4 are a few days of work, fully testable, and they close the real risks
(hallucinated quantities, inconsistent errors, unusable latency UX).

## 2.5 Running LangGraph as a comparison arm (the ADR-003 method, reused)

The value of ADR-003 wasn't the orchestrator — it was the *method*: keep both paths alive behind
a flag, measure the same inputs through each, and publish honest numbers including what didn't
improve. Reuse it exactly.

**Setup**
- Flag: `AGENT_RUNTIME = "orchestrator" | "langgraph"` in `config.py` (alongside the existing
  `USE_ORCHESTRATOR`), default unchanged. Both paths stay in the tree — no deletion until a
  decision is explicit, per the ADR-003 Action Item 8 lesson.
- The LangGraph arm implements the **same** contract: same endpoints, same response shapes.
  If the contract differs, the comparison is invalid.
- Shape for the arm: `parse_meal` as a node, plus a `validate_repair` node, so the graph has
  something real to express. Nodes are pure `State → partial State`; only `parse_meal` calls a model.

**What to measure (per arm, same inputs, ≥3 runs, report median)**
| Metric | Source | Why it matters |
|---|---|---|
| Latency p50/p95 per request shape | `evals/latency_comparison.py --arm <name>` | the headline ADR-003 number; 3 runs not 1 (the one honest complaint about the original measurement) |
| Eval accuracy | `run_eval.py --gate --baseline` | must be **flat** — same prompt, same model, so any movement is a bug in the arm, not a win |
| Tokens / request | provider callback | cost is a production metric; ADR-003 never measured it |
| Lines of code + files touched | `git diff --stat` | the maintainability half of the tradeoff, stated as a number instead of a vibe |
| Failure behaviour | fault-injection test (model 429s, malformed JSON) | which arm fails loudly vs silently — ADR-003's most valuable finding was of this kind |
| Debuggability | honest prose + one trace screenshot each | not quantifiable; say so rather than faking a metric |

**Predictions to write down *before* running** (this is the discipline that made
`NOTES-orchestrator-vs-react.md` worth reading — it lets you be wrong in public and learn):
- Latency: **flat.** Both do one LLM call; graph overhead is microseconds against a 9–40s
  network call. If LangGraph looks faster, suspect measurement error, not magic.
- Accuracy: flat by construction.
- Tokens: identical.
- LOC: LangGraph arm is probably *larger* for a single-call pipeline. That's the honest cost.
- Where it should win: structured tracing per node, streaming stages, and the ability to add a
  node without rewriting control flow — i.e. **its payoff is in change-cost, not runtime**, which
  is exactly what the IFCT pipeline (§8 Trigger A) will test.

📘 **Learn this — a comparison with a predicted-flat result is still worth running**, as long as
you predict it first. It tells you the cost of the abstraction when the benefit is zero, which is
the number you actually need in order to judge whether the benefit is worth it later. What makes
it science rather than advocacy is writing the prediction down before the run.

## 3. Small-model tactics (unchanged — these matter more than the framework)

1. **Narrow schema + enums** over free-text fields. Every enum removes a hallucination class.
2. **Validate → repair-with-feedback → give up.** One repair, with the validator's message
   included. Never silently coerce.
3. **Never let the model do arithmetic.** `total_kcal` should be summed in Python from
   `items[]`, not taken from the model's own total — the model's sum and its items can
   disagree, and Python's answer is free and always right. *(Worth checking whether the
   current code trusts the model's `total_kcal`; if so that's a real bug.)*
4. **Ask the user rather than guess — but ask in the UI, not the server.** Low-confidence or
   missing-quantity items come back flagged; the *client* prompts for a correction. This gets
   you the benefit of slot-filling with no server state, no checkpointer, no interrupt.
5. **Bound everything.** Per-call timeout, bounded retries, bounded fallback chain. A loud
   504 beats a plausible wrong number.
6. **Few-shot from golden data**, versioned with the prompt so the eval report is comparable.
7. **Prompts are versioned files** (`prompts/parse_meal_v3.md`), version recorded in evals.

## 4. Persistence

- Nothing server-side for v1. Profile and meals live client-side per
  `frontendidea.md:104-107` (SharedPreferences: `user_profile`, `calorie_goal`,
  `meals_YYYY-MM-DD`). Already decided; don't revisit.
- When `save_meal` / `get_daily_summary` (README Steps 5–6) land, they are two ordinary
  endpoints plus a table. Still no graph needed.
- A LangGraph **checkpointer** is for conversation state. You have no conversation. Skip.

## 5. Error taxonomy (do this regardless of framework)

```python
class AgentError(BaseModel):
    kind: Literal["upstream_unavailable","upstream_timeout","upstream_bad_response",
                  "model_output_invalid","out_of_scope","internal"]
    message: str                 # user-safe
    retryable: bool
    detail: str | None = None    # dev-only, omitted in prod responses
```
`backend-engineer` maps `kind` → status in **one** exception handler, which also normalizes
FastAPI's Pydantic validation errors (`{"detail": [...]}`) into the same envelope so the
Flutter client handles exactly one shape. (`out_of_scope` covers "this text isn't food".)

## 6. Streaming the 9–40 s wait

For a single-LLM-call endpoint you don't need graph event streaming. Either:
- **Simplest:** keep `POST /api/parse-meal` synchronous, and fix the UX client-side — a
  determinate-ish progress affordance plus "this takes ~20s" copy. Zero backend change.
- **Better:** `POST /api/parse-meal/stream` returning SSE with coarse stages
  (`{"event":"stage","name":"calling_model"}` → `{"event":"final","data":…}`), implemented
  with `StreamingResponse` over an async generator.

Revisit `astream_events` only if a pipeline gains real multi-step structure (§7).

## 7. What to keep from ADR-005 (the bugs were real, the architecture was premature)

| ADR-005 item | Verdict |
|---|---|
| All-or-nothing profile discard bug | ✅ Fix — but it's now moot on the shipped path; guard it in `/api/agent` or delete that path |
| `iterations_used` meaning silently changed | ✅ Fix the contract ambiguity (add `pipeline_steps_run`, keep alias) — cheap, additive |
| TDEE divergence unguarded by a test | ✅ **Keep, highest value.** A permanent regression test for the bug that motivated ADR-003 |
| Eval-parity gap (`extract_request_fields` bypassed) | ⚠️ Becomes moot if extraction leaves the shipped path. Close Phase 2a's gate, then stop |
| Structured logging + correlation id + trace records | ✅ Keep in full, framework-independent |
| `llm_call` one-retry wrapper | ✅ Keep; improve with validator feedback (§3.2) |
| `Intent` enum, `Handler` protocol, `HANDLERS` registry, bounded ReAct | ⏸️ **Defer.** Correct design, wrong time. Revisit with §8 |

## 8. Where LangGraph stops being an experiment and becomes the obvious choice

§2.5 runs it as a measured arm on a simple pipeline. These two triggers are where it wins on
merit rather than on curiosity — and the second one is also the strongest LangGraph practice:

**Trigger A — IFCT nutrition grounding** (`archdocs/RESEARCH-indian-nutrition-data.md`, the
likely ADR-007). That pipeline is genuinely multi-node with a deterministic middle:

```
meal_text → [LLM: decompose dish → ingredients + grams]
          → [deterministic: IFCT table lookup per ingredient]
          → [deterministic: sum calories/macros]
          → items[] + total_kcal
```
Three+ nodes, mixed LLM/deterministic, a real retry/repair boundary, and a per-node latency
story worth streaming. **This is where `StateGraph`, typed state, `astream_events` and
per-node tracing pay for themselves** — and it's the same shape you'd reuse in future
products (RAG, multi-step extraction). It's also behind a flag (`USE_IFCT_GROUNDING`) and
eval-gated, so it's a safe place to learn the framework properly.

**Trigger B — a real conversational surface.** If you decide CalAI should accept "I had two
rotis and dal for lunch, and I'm 3kg lighter than last month" as free text, then extraction,
intent routing, slot-filling and `interrupt()` all become necessary — and *that* is when the
original design in this file's first version is right. It needs a chat UI designed first
(`ui-engineer`), and it should be a deliberate product decision, not a side effect of
backend refactoring.

**Learning note:** you wanted LangGraph practice, and Trigger A gives it to you on a real
pipeline with a real accuracy metric to prove it worked — which is far better practice than
wrapping a single LLM call in a graph to have used a graph.

## 9. Testing (adjust for the smaller scope)

- **L1:** `calc` exact values (exists) + `compose`/summing logic + error-kind → status mapping.
- **L2:** `/api/parse-meal` with **recorded** model responses per prompt version: happy path,
  malformed JSON → repair → success, malformed twice → `model_output_invalid`, unknown enum,
  non-food text → `out_of_scope`, negative calories rejected.
- **L3:** contract tests — every route's valid/invalid/missing-field cases return the *one*
  envelope; CORS headers present.
- **L4:** ADR-004 eval gate for `parse_meal` (exists). **No extraction dataset needed** unless
  Trigger B happens — that removes G16's extraction-eval work from the near-term plan.
- **Termination/limits:** per-call timeout respected; fallback chain exhaustion → 503.
- See `05-testing-and-evals.md` §3.1 (rows P1–P13) — all still apply, unchanged.

## 10. Net effect on the action plan

Step 5 shrinks from "port the orchestrator to LangGraph" to **"harden `/api/parse-meal` +
typed errors + streaming, and defer the router"**, and the LangGraph learning moves to the
IFCT pipeline (new Step 5b / ADR-007). `07-action-plan.md` reflects this.
