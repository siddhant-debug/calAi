# ADR-008: Multi-Turn Slot-Filling During Onboarding — Full-Transcript Re-Extraction

**Status:** Accepted — implemented and shipped in `ddca2e6`. Backend (`schemas.py`, `api/routes.py`, `services/agent_service.py`) and frontend (`api_service.dart`, `user_provider.dart`) both `reviewer`-passed, 144/144 pytest + 28/28 flutter test. Verified live on the iOS Simulator against a locally-run backend on 2026-09-14: the two-turn conversation that previously re-asked for already-given fields now reaches `profile_confirmation` with all six fields and a computed target.
**Date:** 2026-09-14
**Deciders:** Siddhant Tomar
**Companions:** ADR-003 (multiagent split — defines `extract_request_fields` as the single-shot structured-extraction call this ADR extends, not replaces), ADR-005 (router/handler registry — `SlotFillPayload.missing` naming reused unchanged), ADR-007 (`AgentRequest`/`AgentResponse` shape and client-side-persistence pattern — this ADR adds one more additive `AgentRequest` field on the same "backend stays stateless per-request, client owns context" model ADR-007 Part 3 established)

---

## Context

`/api/agent`'s onboarding slot-filling is broken across turns, reproduced live against the running local backend: a user provides `weight_kg`/`height_cm`/`age` in one message; the agent correctly asks only for the still-missing `gender`/`activity_level`/`goal`. The user answers those in the *next* message — and the agent's following question asks for `weight_kg`/`height_cm`/`age` again, even though they were given two turns earlier. Onboarding cannot complete in more than one round without the user re-typing everything they already said, which is a broken first-run experience for a feature whose entire job is collecting a profile across exactly this kind of multi-message exchange.

Root cause, confirmed by reading the code: `extract_request_fields(message: str, llm)` (`calai_backend/services/agent_service.py:129`) is a single-shot LLM extraction over only the current message string — no history is passed in. Per `ParsedRequest`'s own docstring (`schemas.py:129-132`), `profile` is populated "only when the message contains ALL of CalcRequest's required fields... Otherwise None" — extraction is deliberately all-or-nothing *per message*, by design (ADR-003's pattern). That design is fine for a single self-contained message; it silently assumes every message is self-contained, which onboarding's actual multi-turn Q&A shape violates. Two contributing gaps compound it:

- `SlotFillPayload` (`schemas.py:48-51`) returns only `missing: list[str]` — never what *was* extracted from the current message — so even a client willing to accumulate state has nothing to accumulate from the server's response.
- `AgentRequest.profile` (`schemas.py:24-28`) already exists but is documented and implemented (`api_service.dart`'s `agent()`, only sent when `profile.isComplete`) as the *post-onboarding confirmed* profile, not an in-progress partial one — so it's structurally unusable for this bug today, by design, not by omission.
- `OnboardingNotifier.sendMessage` (`calai_frontend/lib/providers/user_provider.dart:59`) sends only the latest raw message text on every call — no accumulation of prior turns at all, client or server side.

Cost of not fixing: onboarding — the single flow every new user must complete before the app is usable at all — cannot survive being split across more than one message, which real conversational answers naturally are (people answer "I'm 30, male" then "moderately active, want to lose weight" as two separate thoughts, not one run-on sentence). This is not a polish issue; it's a correctness bug in the first flow every user hits.

---

## Non-Goals

- Does not change the "profile is all-or-nothing per extraction call" semantics from ADR-003 — extraction remains a single clean LLM call producing a complete-or-`None` profile; this ADR changes *what text* that call sees, not the shape of its output.
- Does not introduce a server-side session/conversation store. The backend stays fully stateless per-request, consistent with ADR-007 Part 3's local-first, client-owns-context model — history is resent by the client, not persisted server-side.
- Does not touch meal-logging slot-filling or `parse_meal`/`MealParseAgent` — meal text is a single self-contained utterance by product design ("I ate two eggs and toast"), not a multi-turn Q&A the way profile onboarding is. Out of scope.
- Does not change `SlotFillPayload`'s shape (still just `missing: list[str]`) — Option A below makes that unnecessary; see Decision.
- Does not set a hard token/message cap or general-purpose long-conversation policy. Onboarding is bounded by construction (6 required profile fields, realistically 2-4 turns) — a real unbounded-conversation cost model is a different, future problem this ADR does not need to solve.
- Does not change `AgentRequest.profile`'s existing meaning (confirmed profile) or when the client sends it.

---

## Decision

**Option A: re-extract over the full onboarding transcript each turn.** The client accumulates every user message sent during the current onboarding session and resends the full ordered list on every `/api/agent` call; the backend's extraction prompt runs over the whole list, not just the newest message. No merge/accumulation logic is added anywhere — the existing "one clean LLM call, all-or-nothing profile" pattern from ADR-003 is preserved unchanged in shape, just fed more input text.

### Backend contract (`backend-engineer` + `ai-engineer`)

`calai_backend/schemas.py` — additive field on `AgentRequest`:

```python
class AgentRequest(BaseModel):
    message: str
    profile: CalcRequest | None = None
    trigger: Literal["message", "weekly_checkin"] = "message"
    conversation_history: list[str] | None = None
    """Prior USER messages from the current onboarding session, oldest first,
    NOT including `message` itself (that stays in `message`, unchanged from
    today's contract). Populated by the client only while onboarding is
    in progress (before `profile` has been confirmed via `/api/calculate`
    + `storage_service.saveProfile`). None or empty on the first turn of a
    session, and on any call made after a profile is already confirmed
    (that path already sends `profile` instead — see ADR-007 Part 3).
    Agent-authored messages (questions the assistant asked) are NOT
    included — only what the user said, since those are the only messages
    that can carry extractable profile fields."""
```

`calai_backend/services/agent_service.py`:

```python
def extract_request_fields(
    message: str,
    llm: BaseChatModel | None,
    conversation_history: list[str] | None = None,
) -> ParsedRequest:
    ...
```

`conversation_history` is a new **optional, defaulted** parameter — every existing call site (`_run_agent_orchestrator`, all of `tests/test_agent_service.py`, `tests/test_intent_classification_eval.py`) keeps compiling and passing unchanged with zero edits, since they omit it and get today's single-message behavior.

Internally: build `all_messages = (conversation_history or []) + [message]`; format `EXTRACTION_PROMPT` over all of them instead of the single `{message}` placeholder, e.g.:

```
Conversation so far (oldest first). Extract fields from ALL messages combined —
a field mentioned in an earlier message and never contradicted later is still present.
If the same field is stated more than once with different values, the LAST stated
value wins (the user corrected themselves).

Message 1: {msg_1}
Message 2: {msg_2}
...

Return ONLY a valid JSON object with this exact structure ...
```

(`meal_text`/`meal_type`/`intent` extraction still reads as "the current turn's intent" — only the newest message's content should populate those three fields, since a stale meal mention from three turns ago should not resurface as "log this meal" again. The prompt separates "extract profile fields from the full transcript" from "extract meal_text/meal_type/intent from message N (the last one)" as two distinct instructions, not one blanket "use everything.")

`_run_agent_orchestrator` (`agent_service.py:285`) and its public wrapper `run_agent` gain the same additive `conversation_history: list[str] | None = None` parameter and thread it straight into the `extract_request_fields` call at line 337.

`calai_backend/api/routes.py`'s `/api/agent` handler (line 96-111) passes `req.conversation_history` through:

```python
return run_agent(
    req.message, None, profile=req.profile, trigger=req.trigger,
    conversation_history=req.conversation_history,
)
```

No change to `AgentResponse`, `SlotFillPayload`, or any other schema — the fix is entirely in what text goes *into* the existing extraction call, not a new field coming out of it.

### Frontend contract (`flutter-engineer`)

`calai_frontend/lib/providers/user_provider.dart`'s `OnboardingNotifier`:

```dart
Future<void> sendMessage(String text) async {
  final current = state.value ?? [];
  final withUserMessage = [...current, ConversationMessage.user(text)];
  state = AsyncValue.data(withUserMessage);

  // All prior USER messages this session, oldest first, excluding `text` itself
  // (matches AgentRequest.conversation_history's contract exactly).
  final priorUserMessages = current
      .where((m) => m.isUser)
      .map((m) => m.text)
      .toList();

  try {
    final response = await ref.read(apiServiceProvider).agent(
      text,
      conversationHistory: priorUserMessages.isEmpty ? null : priorUserMessages,
    );
    state = AsyncValue.data([...withUserMessage, ConversationMessage.agent(response)]);
  } catch (e) {
    ...
  }
}
```

(Exact `ConversationMessage` field names — `isUser`/`text` above are illustrative; `flutter-engineer` uses whatever the existing model actually exposes, verified by reading `calai_frontend/lib/models/conversation_message.dart` before implementing — this ADR does not restate that file's shape.)

`calai_frontend/lib/core/api_service.dart`'s `agent()` gains a matching optional parameter:

```dart
Future<AgentResponse> agent(
  String message, {
  UserProfile? profile,
  String trigger = 'message',
  List<String>? conversationHistory,
}) async {
  final json = await _post('/agent', {
    'message': message,
    if (profile != null && profile.isComplete) 'profile': profile.toJson(),
    'trigger': trigger,
    if (conversationHistory != null && conversationHistory.isNotEmpty)
      'conversation_history': conversationHistory,
  });
  return AgentResponse.fromJson(json);
}
```

Once `UserNotifier.confirm()` succeeds and a profile is persisted, onboarding is complete and `OnboardingNotifier`/`sendMessage` is no longer the code path in use for profile questions (post-onboarding messages send `profile` instead, per ADR-007) — no explicit "clear history" step is needed since `OnboardingNotifier`'s state is session-scoped and not reused after onboarding finishes.

---

## Options Considered

### Option A: re-extract over the full transcript each turn — Chosen

As described in Decision.

| Dimension | Assessment |
|---|---|
| Effort | Low — one additive optional param on 3 backend functions + 1 schema field, one prompt edit, one additive Dart param + one list accumulation in an existing notifier |
| Correctness robustness | High — a field can never be "lost" once mentioned, because every call re-derives the full profile from everything ever said. There is no merge step to have a bug in. |
| Fits existing pattern | Yes — `extract_request_fields` remains exactly ADR-003's "one clean single-shot LLM call, all-or-nothing profile," just fed a longer input string. No new response shape, no new merge semantics. |
| Cost per call | Slightly larger prompt as the conversation grows — bounded (onboarding is ~6 required fields, realistically 2-4 turns; not an open-ended chat) |
| New moving parts | None beyond "send a list instead of a string" |

### Option B: accumulate partial fields turn-by-turn — Rejected

`SlotFillPayload` gains a field returning whatever fields *were* extracted from the current message even if incomplete; client accumulates these into a running partial profile and sends it back (fixing the `profile.isComplete` gate that currently blocks `AgentRequest.profile` from being usable mid-onboarding); backend merges client-supplied partial + newly-extracted fields, then computes `missing` against the merge.

| Dimension | Assessment |
|---|---|
| Effort | Medium-high — new response field, a new partial-profile shape distinct from `CalcRequest` (all fields must become optional mid-accumulation, so it can't just reuse `CalcRequest`), two-directional merge logic (client merges server's partial into its running state; server merges client's partial with the current message's newly-extracted fields) |
| Correctness robustness | Lower — merge logic is exactly the class of code that reintroduced this bug's symptom once already (a field silently dropped because one side of a merge didn't carry it forward). A careless merge (e.g. overwriting rather than filling-null-only) can re-lose a field the same way the current bug does, just one layer deeper. |
| Fits existing pattern | No — introduces a genuinely new "partial profile" shape and a stateful-merge responsibility neither `agent_service.py` nor `AgentRequest`/`AgentResponse` has today; a step away from ADR-003's single-shot-extraction discipline, not a continuation of it |
| Cost per call | Lower per-call payload (only new fields sent, not full history) — the one real advantage over Option A |
| Resume/narrative value | Weaker — "added bidirectional merge logic to fix a state-loss bug" reads as treating the symptom's mechanism (partial state, imperfectly carried forward) rather than removing it |

**Rejected:** solves a payload-size concern nobody has raised (onboarding transcripts are a handful of short messages, not a real bandwidth problem) at the cost of introducing new merge logic in exactly the shape of code that caused this bug in the first place. Revisit only if onboarding conversations become long enough that resending full history is a measured, not hypothetical, cost.

### Option C: pass full role-tagged message history (assistant + user turns), not just user text — Considered, not adopted

Send the whole `ConversationMessage` list (both agent questions and user answers) instead of only user messages, letting the LLM see its own prior questions as context.

| Dimension | Assessment |
|---|---|
| Effort | Marginally higher — role-tagged shape instead of `list[str]` |
| Value over Option A | None identified — the agent's own questions carry no field values the user hasn't already stated in their own messages; the only extractable signal is what the *user* said |
| Cost | More tokens per call for no extraction-accuracy benefit |

**Rejected:** no evidence it fixes anything Option A doesn't, at a strictly higher cost. Worth revisiting only if intent classification (not slot-filling) ever needs assistant-turn context to disambiguate an otherwise-ambiguous user reply — not the case for the bug this ADR fixes.

---

## Consequences

**Becomes easier:**
- Onboarding can complete correctly across any number of turns — the class of bug (a field silently forgotten) is structurally prevented, not patched, because there is no accumulation step to have a bug in.
- No new schema shapes for engineers or `reviewer` to reason about beyond one additive list field.

**Becomes harder:**
- The client must track and resend the full onboarding message history on every turn (a small but real new responsibility in `OnboardingNotifier`, not present today).
- Prompt size grows with conversation length during onboarding — bounded today, but a future onboarding redesign that makes the conversation open-ended (rather than a fixed set of profile fields) would need to revisit this.
- `extract_request_fields`'s prompt now has two distinct instructions (profile fields from the full transcript; `meal_text`/`meal_type`/`intent` from only the latest message) instead of one uniform instruction — slightly more prompt-engineering surface for `ai-engineer` to get right and for `tester` to cover.

**Revisit later:**
- If onboarding is ever redesigned to be genuinely open-ended (not a fixed 6-field profile), full-transcript resend's cost model should be re-evaluated — that's a new ADR, not a default evolution of this one.

---

## Action Items

1. [ ] `calai_backend/schemas.py`: `AgentRequest.conversation_history: list[str] | None = None` added exactly as specified — verify: `python -c "from calai_backend.schemas import AgentRequest; assert AgentRequest(message='hi').conversation_history is None"`. — `backend-engineer`
2. [ ] `calai_backend/api/routes.py`'s `/api/agent` handler passes `req.conversation_history` through to `run_agent` — verify: `grep -n "conversation_history" calai_backend/api/routes.py` shows it passed at the `run_agent(...)` call site. — `backend-engineer`
3. [ ] `extract_request_fields` gains the additive `conversation_history: list[str] | None = None` parameter; all existing call sites (`_run_agent_orchestrator`, every test in `test_agent_service.py` and `test_intent_classification_eval.py`) compile and pass unmodified — verify: `pytest calai_backend/tests/ -v` passes with zero edits to any existing `extract_request_fields(...)` call in the test files (`git diff calai_backend/tests/test_agent_service.py calai_backend/tests/test_intent_classification_eval.py` shows no changes). — `ai-engineer`
4. [ ] `EXTRACTION_PROMPT` updated so profile fields are extracted from the full combined transcript while `meal_text`/`meal_type`/`intent` are extracted from only the latest message — verify: read `calai_backend/services/agent_service.py`'s updated `EXTRACTION_PROMPT` and confirm it contains this distinction explicitly, not one blanket instruction. — `ai-engineer`
5. [ ] `_run_agent_orchestrator`/`run_agent` thread `conversation_history` into the `extract_request_fields` call — verify: `grep -n "extract_request_fields(message, llm, conversation_history" calai_backend/services/agent_service.py` (or equivalent kwarg form) returns a match. — `ai-engineer`
6. [ ] New regression test reproducing the exact reported bug: turn 1 sends weight/height/age only (`conversation_history=None`), asserts `profile is None` and `missing` covers gender/activity_level/goal; turn 2 sends gender/activity_level/goal with `conversation_history=[<turn 1's message>]`, asserts `parsed_request.profile is not None` and all 6 fields are populated — verify: new test exists in `calai_backend/tests/test_agent_service.py` and `pytest calai_backend/tests/test_agent_service.py -v -k conversation_history` passes. — `tester`
7. [ ] New permanent case added to `evals/dataset/*.jsonl` if the eval harness's dataset format supports multi-turn cases; if `parse_meal_text`/the eval harness only scores single-message extraction (confirm by reading `evals/README.md` or dataset schema), explicitly note in the test file that this bug is covered by the pytest regression test in Action Item 6, not the eval harness, and why — verify: either a new dataset entry exists, or a one-line comment in `test_agent_service.py` states the eval harness doesn't cover multi-turn slot-filling and this pytest case is the permanent regression guard. — `tester`
8. [ ] `calai_frontend/lib/core/api_service.dart`'s `agent()` gains `List<String>? conversationHistory` and includes it as `conversation_history` in the POST body only when non-null and non-empty — verify: `dart analyze lib/core/api_service.dart` reports no errors; `git diff` shows the added parameter and conditional body key exactly as specified above. — `flutter-engineer`
9. [ ] `OnboardingNotifier.sendMessage` accumulates prior user-message texts from `state.value` and passes them as `conversationHistory` on every `agent()` call after the first — verify: `dart analyze lib/providers/user_provider.dart` reports no errors; a manual two-turn run against the local backend (weight/height/age, then gender/activity/goal) confirms the agent does NOT re-ask for the first three fields. — `flutter-engineer`
10. [ ] Full existing suite passes unmodified except for the one new regression test — verify: `pytest calai_backend/tests/ -v` exits 0. — `backend-engineer` + `ai-engineer`

---

## Open Questions

None — this is a pure bug fix with a technical root cause (stateless single-message extraction) and no open product question; both rejected options were evaluated on engineering merit alone.
