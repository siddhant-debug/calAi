# ADR-007: `/api/agent` Structured Response Shape and Client-Side Persistence

**Status:** Accepted — Action Items 1-9 (backend: schema + service logic + tests) implemented, 142/142 tests passing, under `reviewer` fix-loop as of 2026-09-14 (docs-sync findings, not code bugs). Action Items 10-12 (frontend: `storage_service.dart`, `agent_message.dart`, `ui-engineer`'s SKILL.md table update) pending.
**Date:** 2026-09-14
**Deciders:** Siddhant Tomar
**Companions:** ADR-001 (system architecture — defines `/api/agent`'s role), ADR-003 (multiagent split — `compose_response`/`AgentResponse` construction this ADR extends, `agent_service.py:180-320`), ADR-005 (router/handler registry — `Intent`, `StepResult`/`NeedsMoreInfo.missing` naming this ADR reuses; also proposes an as-yet-unimplemented `AgentResponse.pipeline_steps_run` field this ADR's schema must coexist with, not collide with)

---

## Context

`flutter-engineer` cannot finish 2 of the ~14 files the v1 diary spec (`skills/flutter-dev/SKILL.md`) calls for — the real (non-placeholder) `widgets/agent_message.dart` and `core/storage_service.dart` — because both depend on decisions that were never formally made. The spec's own "Decisions pending" table (lines 108-111) marks both rows "Open — ADR-007's job," and until now `archdocs/` stopped at ADR-006. Concretely, today:

1. **`AgentResponse` (`calai_backend/schemas.py:26-28`) is `{response: str, iterations_used: int}` — a single prose string.** The spec requires the UI to distinguishably render four different message kinds from whatever `/api/agent` returns (a slot-filling question, a profile-confirmation prompt with a computed calorie preview, a recommendation, and a weekly weight check-in prompt asking for current weight — SKILL.md lines 41-42, 66-72, 307-329). A bare string cannot carry the profile-preview numbers the confirmation card needs to render (`Daily target 2,340 kcal`, SKILL.md line 320) without the client re-deriving them itself or `flutter-engineer` inventing a fragile prose-parsing scheme no one signed off on.
2. **`storage_service.dart` is a 0-byte file today**, and nothing in the codebase says whether it should read/write `SharedPreferences` or call a not-yet-existing server API. `flutter-engineer` cannot write `user_provider.dart` or `meal_provider.dart` against an undecided storage backend, and per SKILL.md line 79-84 this is explicitly called out as blocking, not a UI question.
3. **Every other file in the v1 spec is unblocked; these two specifically are not** — this is the last blocker on a complete frontend build-out, per this ADR's input brief (`plans/adr007-agent-response-persistence-brief.md`).

Both decisions have a live downstream consumer (`flutter-engineer`) who needs one settled, concrete answer — not two independently-guessed shapes from `ai-engineer`/`backend-engineer` on one side and `flutter-engineer` on the other that then have to be reconciled after the fact.

---

## Non-Goals

- This does not change `/api/calculate` or `/api/parse-meal`'s request/response shapes — untouched, out of scope.
- This does not implement `agent_message.dart`, `storage_service.dart`, `schemas.py`, or `agent_service.py` — that is `flutter-engineer`/`backend-engineer`/`ai-engineer`'s job once this ADR lands, per the input brief's explicit exclusion.
- This does not decide the exact prompt wording, confirmation-vs-recommendation trigger heuristics, or weekly-check-in cadence business logic beyond the "weekly" cadence the UI spec already names (SKILL.md line 42) — those are `ai-engineer` orchestration details built against the contracts below, not JSON-shape decisions.
- This does not introduce accounts, login, or a `user_id` field anywhere. No auth exists in `calai_backend/` today (verified: no `user_id` field on any model in `schemas.py`), and this ADR does not add one.
- This does not reopen any UI-shape decision the v1 pivot already resolved (multi-item rendering, entry-card states, day-ring retirement, `meal_type` affordance, in-flight-state styling — SKILL.md "Decisions pending," rows resolved by that spec) — closed, not touched here.
- This does not fix `plans/v1-product-brief.md`'s dangling citations (the file is referenced 5 times across the repo but doesn't exist) — a real, separate documentation-integrity defect, tracked but out of this ADR's scope per the input brief.

---

## Decision

### Part 1 — `/api/agent` structured response shape (additive, not breaking)

Add a `message_type` discriminator plus four optional, mutually-exclusive typed payload fields to `AgentResponse`. `response: str` and `iterations_used: int` are **retained unchanged** — every existing caller reading only those two fields keeps working exactly as today; this is a pure superset.

`calai_backend/schemas.py` (backend-engineer):

```python
class AgentMessageType(str, Enum):
    """Mirrors the Intent enum's (str, Enum) pattern (schemas.py). Discriminates
    which of AgentResponse's four optional payload fields, if any, is populated.
    Exactly one of {slot_fill, profile_confirmation, recommendation, weekly_checkin}
    is non-None when message_type != INFO; all four are None when message_type == INFO."""
    INFO = "info"                                # plain text, no structured payload (default;
                                                   # preserves today's behavior for old callers)
    SLOT_FILL_QUESTION = "slot_fill_question"
    PROFILE_CONFIRMATION = "profile_confirmation"
    RECOMMENDATION = "recommendation"
    WEEKLY_CHECKIN = "weekly_checkin"


class SlotFillPayload(BaseModel):
    missing: list[str]
    """Exact field-name list, reusing ADR-005's NeedsMoreInfo.missing naming and
    contents verbatim (not re-derived) when the orchestrator/handler layer already
    computes it. DEPENDENCY NOTE: ADR-005's handler-registry refactor is mid-flight,
    not fully landed as of this ADR — if NeedsMoreInfo does not yet concretely exist
    in agent_service.py when Action Item 4 is picked up, ai-engineer builds this list
    independently (same semantics: which of the profile fields are still missing) and
    reconciles naming with ADR-005 once it lands, rather than blocking on it."""


class ProfileConfirmationPayload(BaseModel):
    profile: CalcRequest
    """The fully-extracted, not-yet-confirmed profile — same shape /api/calculate
    accepts, so 'Confirm' in the UI (SKILL.md line 329) can POST this object to
    /api/calculate unchanged."""
    preview: CalcResponse
    """bmr_kcal/tdee_kcal/calorie_goal_kcal computed from `profile` via the same
    deterministic calc pipeline /api/calculate uses (ADR-003's run_calc_pipeline),
    so the confirmation card can show 'Daily target 2,340 kcal' (SKILL.md line 320)
    before the user has confirmed anything. Computing this preview does not persist
    or confirm the profile."""


class RecommendationPayload(BaseModel):
    calorie_goal_kcal: float
    tdee_kcal: float
    bmr_kcal: float
    rationale: str
    """Short human-readable reason for the recommendation, e.g. 'Your last 3 weigh-ins
    are trending faster than your 0.5kg/week goal.' Always present — a bare number with
    no reason is not a usable recommendation message."""


class WeeklyCheckinPayload(BaseModel):
    last_weight_kg: float | None = None
    """Most recent weight on record, if any (client-supplied via AgentRequest.profile
    or prior weight history) — lets the UI pre-fill or reference it in the prompt.
    None on a client's very first check-in."""


class AgentResponse(BaseModel):
    response: str
    """Unchanged. Always present — a human-readable fallback string regardless of
    message_type, so any client that only ever read this field (today's contract)
    continues to work with zero changes."""
    iterations_used: int
    """Unchanged field name and meaning — see ADR-005's iterations_used/pipeline_steps_run
    resolution if/when that ADR's Action Items land; this ADR does not alter that decision,
    it only adds the fields below alongside it."""
    message_type: AgentMessageType = AgentMessageType.INFO
    slot_fill: SlotFillPayload | None = None
    profile_confirmation: ProfileConfirmationPayload | None = None
    recommendation: RecommendationPayload | None = None
    weekly_checkin: WeeklyCheckinPayload | None = None
```

**Discriminator contract flutter-engineer codes against:** switch on `message_type`; read exactly the one payload field matching it; treat all four payload fields as `None` (plain `response` text only) when `message_type == AgentMessageType.INFO`. Server-side, `ai-engineer`'s composing code (`agent_service.py::compose_response` or its ADR-005 handler successors) must never set more than one payload field non-`None` on a given response — `reviewer` treats two simultaneously non-`None` payload fields as a bucket-1 bug, not a style nit.

**Failure mode when composing a payload fails:** if the LLM call or `run_calc_pipeline` invocation backing any of the four payload types raises partway through composition (malformed LLM output, a NIM timeout, a `ValueError` from the calc pipeline), `agent_service.py` degrades to an `AgentMessageType.INFO` response with a plain-language `response` string describing the failure (e.g. "I couldn't confirm your profile right now — try again in a moment.") rather than propagating an unhandled exception. This is a deliberate choice, not the `/api/agent` route's current unhandled-500 behavior carried forward unexamined: a structured-payload failure is a degraded-but-still-useful response (the user gets *some* reply), not a hard error the client has no way to render. `flutter-engineer`'s `agent_message.dart` therefore never needs a fifth "error" branch beyond `INFO` — a failed structured response and a plain conversational one are the same shape to the client.

**Logging:** every branch that sets `message_type` to a non-`INFO` value is a decision point under the existing ADR-005/`rules/backend-facts.md` logging contract — `ai-engineer` logs at DEBUG with the standard fields (`intent`, `step`/`handler`, `outcome`, `latency_ms`, correlation id), plus `message_type` itself as an additional field so a trace can be filtered by which of the five response kinds fired. The payload-composition failure case above logs at WARNING, `outcome="fallback"`, matching the existing convention for a degraded-but-non-fatal path. This is not optional per `reviewer`'s existing gate (a decision point with no logging is a bucket-1 finding) — stated explicitly here so it isn't rediscovered at review time.

### Part 2 — `AgentRequest` gains optional context fields (additive)

Because persistence is client-side (Part 3) and `calai_backend` has no server-side session/store, the backend cannot itself know "has this client been asked for a profile before" or "is a weekly check-in due" — that state lives on the client. `AgentRequest` gains two optional fields so the backend stays fully stateless per-request while still being able to produce all four message kinds:

```python
class AgentRequest(BaseModel):
    message: str
    profile: CalcRequest | None = None
    """The client's currently-confirmed profile, if any — sent as context on every
    call so the backend can reference it (e.g. weekly_checkin's last_weight_kg,
    recommendation math) without a server-side lookup. None during onboarding,
    before any profile is confirmed."""
    trigger: Literal["message", "weekly_checkin"] = "message"
    """"message" (default): process `message` as free text, exactly today's behavior.
    "weekly_checkin": the client has locally determined a check-in is due (per its
    own stored last-check-in timestamp, per Part 3) and is explicitly requesting a
    weekly_checkin-typed AgentResponse; `message` is ignored server-side in this mode.
    This keeps the "when is a check-in due" date math in exactly one place (the
    client, which already owns the timestamp) rather than duplicating it server-side
    with a second clock."""
```

`message: str` alone (today's only field) remains entirely valid — `profile` and `trigger` both default such that an old-shaped request produces identical behavior to today.

### Part 3 — Persistence model: client-side (`SharedPreferences`), not server-side

**Decision: `UserProfile` and meal-log/weight history persist entirely client-side**, via `SharedPreferences`, matching `storage_service.dart`'s stub role in the spec. No new server-side storage layer, no new `/api/profile` or `/api/meals` endpoints, no `user_id` field anywhere.

**Rationale, evaluated against the input brief's evidence:**
- No auth/accounts exist anywhere in `calai_backend/` today (verified: `grep -rn "user_id" calai_backend/` returns no matches). A server-side store for `UserProfile`/meal history needs *some* way to know whose data it's reading — introducing that identity mechanism is a materially bigger change than this ADR's two questions, and nothing in the input brief, the UI spec, or prior ADRs asks for cross-device sync.
- The project is externally positioned as "local-first" (brief's constraint, existing product framing, not invented here). A server-side data store — even a single-user one with no auth — contradicts that positioning; a local-first nutrition diary keeping its diary server-side is a real inconsistency, not a technicality.
- NVIDIA NIM (ADR-006) being a hosted *inference* call does not imply user *data* storage should also be hosted — the brief is explicit these are separate axes, and this ADR treats them as such: inference already isn't fully local; that does not argue for moving the user's actual data off-device too.

This evidence is judged sufficient to resolve as a technical decision here, per the input brief's own recommendation — not escalated as a `USER-DECIDES` blocker.

**`storage_service.dart` contract** `flutter-engineer` codes against:

```dart
// lib/core/storage_service.dart
class StorageService {
  Future<UserProfile?> loadProfile();
  Future<void> saveProfile(UserProfile profile);
  Future<void> clearProfile();

  Future<List<MealEntry>> loadEntriesForDate(DateTime date);
  Future<void> appendEntry(MealEntry entry, DateTime date);
  Future<void> deleteEntry(String entryId, DateTime date);

  Future<List<WeightSample>> loadWeightHistory();
  Future<void> appendWeightSample(WeightSample sample);

  Future<DateTime?> loadLastCheckinAt();
  Future<void> saveLastCheckinAt(DateTime at);
}
```

Backed by `SharedPreferences` string keys, JSON-encoded: `profile`, `entries_<yyyy-MM-dd>` (one key per date, matching the spec's per-date session model, SKILL.md line 83), `weight_history` (JSON list of `WeightSample`), `last_checkin_at` (ISO-8601 string). `WeightSample` is a new, minimal model: `{ "weightKg": double, "at": DateTime }`. `UserProfile` and `MealEntry` are the existing/spec-named models (`lib/models/user_profile.dart`, `lib/models/meal_entry.dart`) — this ADR does not rename or restructure their fields, only assigns them a storage backend.

`flutter-engineer` is responsible for deciding, at implementation time, whether "is a weekly check-in due" is computed by comparing `loadLastCheckinAt()` against `DateTime.now()` at app-open/session-start (recommended: 7+ days, matching the spec's "weekly" naming) and then issuing `AgentRequest(trigger: "weekly_checkin")` — this exact comparison is implementation detail, not a further architecture decision, since Part 2 already fixes the contract (client decides, server executes).

---

## Options Considered

### Response shape

#### Option A: Discriminated `message_type` + typed optional payload fields ✅ (Chosen)
As described in Decision Part 1.

| Dimension | Assessment |
|---|---|
| Effort | Low-medium — one enum, four small payload models, additive `AgentResponse` fields |
| Distinguishes all 4 message kinds | Yes, unambiguously — `flutter-engineer` switches on one enum, no string parsing |
| Carries computed numbers (calorie preview, etc.) | Yes — `ProfileConfirmationPayload.preview`, `RecommendationPayload`'s three kcal fields are typed floats the UI can format directly |
| Breaking? | No — pure superset of today's `{response, iterations_used}` |
| Resume/narrative value | Consistent with the project's existing pattern (`Intent`, `StepResult`/`NeedsMoreInfo` from ADR-005) rather than a one-off shape |

#### Option B: Keep `response: str` only; client parses prose to detect message kind
Ship no schema change; `flutter-engineer` regexes/keyword-matches the prose string (e.g. "contains 'Daily target'" → treat as confirmation) to decide what to render.

| Dimension | Assessment |
|---|---|
| Effort | Lowest on the backend — zero schema change |
| Distinguishes all 4 message kinds | Fragile — breaks silently the moment `ai-engineer` rewords a prompt/response template; no test can catch a wording drift breaking client parsing |
| Carries computed numbers | No — the UI would have to re-parse "2,340 kcal" out of prose text, or re-derive it client-side from a duplicate calc implementation, doubling a calculation that already exists server-side (`run_calc_pipeline`) |
| Breaking? | No, but defers a real cost onto every future prompt change |
| Resume/narrative value | Weak — "the client regexes the LLM's prose" is not a defensible API design and would be flagged in review |

**Rejected:** solves the "no schema change" goal at the cost of a genuinely fragile, untested coupling between prompt wording and UI behavior — exactly the kind of hidden contract CLAUDE.md's error-envelope-consistency rule and ADR-005's typed-contract precedent argue against.

#### Option C: Single untyped `payload: dict[str, Any]` field, no per-kind schema
Add one generic `payload` dict to `AgentResponse` and let `ai-engineer` and `flutter-engineer` agree out-of-band on its keys per message kind.

| Dimension | Assessment |
|---|---|
| Effort | Lowest schema effort — one field, ever |
| Distinguishes all 4 message kinds | Only via a separate `message_type` string key inside the dict — no Pydantic/Dart-side validation that a given kind's expected keys are actually present |
| Type safety | None — a typo'd key or missing field fails silently or at runtime on the Flutter side, not at the API boundary |
| Resume/narrative value | Weak — abandons the typed-contract discipline ADR-005 already established for this exact codebase (`StepResult`, `HandlerContext`) for no effort savings large enough to justify it |

**Rejected:** the four message kinds are known and fixed today — there's no case for an escape-hatch untyped dict when four concrete Pydantic models fully describe the space and cost barely more to write.

### Persistence model

#### Option A: Client-side, `SharedPreferences` ✅ (Chosen)
As described in Decision Part 3.

| Dimension | Assessment |
|---|---|
| Effort | Low — `storage_service.dart` wraps `SharedPreferences`, no new backend surface |
| Requires auth/accounts | No |
| Matches "local-first" positioning | Yes |
| Cross-device sync | Not possible (explicitly not a goal here or anywhere upstream) |
| New backend endpoints | None |

#### Option B: Server-side store (SQLite in `calai_backend/`), single-user, no auth
Add a `calai_backend/` persistence layer (e.g. SQLite) and `GET`/`POST /api/profile`, `GET`/`POST /api/meals` endpoints, implicitly single-tenant (one row per table, no `user_id`).

| Dimension | Assessment |
|---|---|
| Effort | Medium-high — new storage module, migrations, 4 new endpoints, error-envelope work per CLAUDE.md's normalization rule |
| Requires auth/accounts | Not strictly, if single-tenant — but "single-tenant, no auth" is itself a footgun the moment this backend is ever deployed reachable by more than one device/person, silently mixing data with no isolation |
| Matches "local-first" positioning | No — directly contradicts it |
| Cross-device sync | Yes, if ever wanted — the one real advantage |
| Resume/narrative value | Neutral-to-negative here: "added a single-tenant no-auth data store" reads as an unfinished multi-user design, not a deliberate architecture choice, unless a real multi-user need is stated (it isn't) |

**Rejected:** solves a cross-device-sync need nobody has asked for, at real implementation cost, while contradicting the project's stated positioning and introducing a single-tenant footgun. Revisit only if a real multi-device/multi-user requirement is stated as a product decision — that would itself need a `USER-DECIDES` product call on accounts/auth first, which this ADR does not have evidence to make.

---

## Consequences

**Becomes easier:**
- `flutter-engineer` can finish `agent_message.dart` and `storage_service.dart` immediately — both blocking questions in SKILL.md's "Decisions pending" table are resolved with concrete Dart-codable contracts.
- Adding a fifth message kind later (if the product ever needs one) — new `AgentMessageType` member + one new optional payload field, following the same pattern, no restructuring of existing fields.
- Testing each message kind in isolation — `tester` can assert `message_type` and the one populated payload field per case, rather than string-matching prose.

**Becomes harder:**
- `ai-engineer`'s composing code must maintain the "exactly one payload field non-None per message_type" invariant by discipline — nothing in Pydantic enforces mutual exclusivity across four independent `Optional` fields automatically; this is stated here explicitly as a rule `reviewer` checks, not left implicit.
- The client is now the sole source of truth for profile/history state — a client uninstall, app-data clear, or `SharedPreferences` corruption loses that data outright, with no server-side backup. This is an accepted, stated cost of local-first, not an oversight.
- `AgentRequest.profile`/`trigger` add two fields `ai-engineer`'s orchestration logic must now read and branch on, beyond the single `message` string it handles today.
- Four new payload-composition paths are four new places an LLM call or calc-pipeline invocation can fail — each needs the INFO-degradation + WARNING-log behavior specified in Part 1, not a bare propagated exception. This is more failure-handling surface than the single-string response had, in exchange for the structured contract's benefits above.

**Revisit later:**
- If a real multi-device/cross-account requirement is ever stated as a product decision, Option B (or a proper authenticated server-side store) becomes the right call — that is a new ADR building on an explicit product decision, not a default evolution of this one.
- If `AgentMessageType.INFO` (the "just prose, no structured payload" case) turns out to cover most real traffic, that's a signal the four structured kinds are rarer in practice than the spec's naming suggests — worth noting in a future eval/trace review, not actionable now.

---

## Action Items

1. [ ] `calai_backend/schemas.py`: `AgentMessageType`, `SlotFillPayload`, `ProfileConfirmationPayload`, `RecommendationPayload`, `WeeklyCheckinPayload` added exactly as specified; `AgentResponse` gains `message_type` (default `INFO`) and the four `Optional` payload fields, `response`/`iterations_used` unchanged — verify: `python -c "from calai_backend.schemas import AgentResponse; r = AgentResponse(response='x', iterations_used=1); assert r.message_type.value == 'info' and r.slot_fill is None"`. — `backend-engineer`
2. [ ] `AgentRequest` gains `profile: CalcRequest | None = None` and `trigger: Literal["message", "weekly_checkin"] = "message"` — verify: `python -c "from calai_backend.schemas import AgentRequest; assert AgentRequest(message='hi').trigger == 'message'"` and existing `AgentRequest(message="...")`-only call sites in `calai_backend/tests/` still construct without error. — `backend-engineer`
3. [ ] `calai_backend/api/routes.py`'s `/api/agent` handler signature is unchanged (still takes `AgentRequest`, returns `AgentResponse`) — verify: `git diff calai_backend/api/routes.py` shows no signature change, only pass-through of the two new optional request fields if the handler currently destructures `AgentRequest` field-by-field. — `backend-engineer`
4. [ ] `agent_service.py`'s response-composing code (`compose_response` or its ADR-005 handler successors) sets `message_type` and exactly one matching payload field per response, never more than one non-`None` payload field, `INFO` + all-`None` for the plain-prose case — verify: `tester`'s pytest asserting, for one representative case of each of the 4 kinds plus the plain-info case, that exactly the expected payload field is non-`None` and all others are `None`. — `ai-engineer`
5. [ ] `agent_service.py` reads `AgentRequest.trigger == "weekly_checkin"` and short-circuits to a `WEEKLY_CHECKIN`-typed response (ignoring `message`) when set; reads `AgentRequest.profile` where needed (e.g. `WeeklyCheckinPayload.last_weight_kg`) — verify: `tester`'s pytest sending `trigger="weekly_checkin"` asserts `message_type == AgentMessageType.WEEKLY_CHECKIN` regardless of `message` content. — `ai-engineer`
6. [ ] `ProfileConfirmationPayload.preview` is computed via the same deterministic calc pipeline `/api/calculate` uses (`run_calc_pipeline` or equivalent), not a re-implementation — verify: `grep -n "run_calc_pipeline\|calculate_bmr\|calculate_tdee" calai_backend/services/agent_service.py` shows the confirmation-composing code calling the existing pipeline function, not new duplicate math. — `ai-engineer`
7. [ ] Each of the four payload-composing paths degrades to `AgentMessageType.INFO` with a plain-language `response` string on failure (LLM error, calc-pipeline `ValueError`, NIM timeout) rather than propagating an unhandled exception, per Part 1's failure-mode clause — verify: `tester`'s pytest simulating a failure in each of the four composition paths (e.g. mocking `run_calc_pipeline` to raise) asserts the resulting `AgentResponse.message_type == AgentMessageType.INFO` and all four payload fields are `None`, not a raised exception or a 500. — `ai-engineer`
8. [ ] Every branch setting a non-`INFO` `message_type` logs at DEBUG with the standard fields (`intent`, `step`/`handler`, `outcome`, `latency_ms`, correlation id) plus `message_type`; the Item 7 failure-degradation path logs at WARNING with `outcome="fallback"` — verify: `grep -n "message_type" calai_backend/services/agent_service.py` shows a logging call alongside each branch that sets it, not just the field assignment. — `ai-engineer`
9. [ ] Full existing suite passes unmodified except for necessary additive-field updates — verify: `pytest calai_backend/tests/ -v` passes; `git diff calai_backend/tests/` shows no test asserting the *absence* of `message_type`/payload fields needed rewriting (only additions, since the change is additive). — `backend-engineer` + `ai-engineer`
10. [ ] `calai_frontend/lib/core/storage_service.dart` implements the `StorageService` contract from Decision Part 3 exactly (method names/signatures), backed by `SharedPreferences` — verify: `dart analyze lib/core/storage_service.dart` reports no errors. — `flutter-engineer`
11. [ ] `calai_frontend/lib/widgets/agent_message.dart` renders all four structured message kinds plus the plain-`INFO` case, switching on a Dart-side `AgentMessageType` enum mirroring the backend's — verify: `dart analyze lib/widgets/agent_message.dart` reports no errors; a manual run against each of the 5 `message_type` values (via a mocked `api_service.dart` response) renders the corresponding SKILL.md-specified layout (slot-fill question, confirmation card with preview numbers, recommendation, check-in prompt, plain text). — `flutter-engineer`
12. [ ] `skills/flutter-dev/SKILL.md`'s "Decisions pending" table (lines 108-111) — both rows updated to reference this ADR by number and marked resolved, per `ui-engineer`'s own Definition of Done for that table. — `ui-engineer`

---

## Open Questions

- The exact "days since last check-in" threshold for triggering `trigger="weekly_checkin"` client-side is left at the spec's own "weekly" naming (interpreted as 7+ days) rather than pinned to an exact integer in this ADR — if product wants a different cadence (e.g. exactly 7 days vs. "at least 7, prompted at next app open"), that's a small, non-blocking follow-up clarification for `flutter-engineer`/product, not a reason to hold this ADR.
- `RecommendationPayload`'s trigger conditions (when the agent decides to proactively recommend a calorie-goal change, vs. simply answering a direct question) are intentionally left to `ai-engineer`'s orchestration logic, not specified here — this ADR fixes the JSON shape a recommendation is delivered in, not the heuristic that decides to send one.
