---
name: flutter-test
description: Test the calAI Flutter frontend — widget tests, integration checks, and manual golden-path verification. Use when the user says "test", "write tests", "check if it works", "does the ring render", "test onboarding", "verify the meal input", or asks to validate any Flutter feature. Also trigger on "run the app", "check on simulator", or "does X work on device".
---

# calAI Flutter Test Skill

You are testing the calAI Flutter frontend. Read `skills/flutter-dev/SKILL.md` first — it is
the source of truth for expected behaviour. `archdocs/frontendidea.md` is background intent and
is **not final**; never write a test asserting behaviour that only appears there.

## Project location
`calai_frontend/` — run all commands from inside this directory.

## Step 1 — Static analysis first
Always run before anything else:
```bash
cd calai_frontend && dart analyze lib
```
Fix all errors and warnings before proceeding.
**Never `flutter analyze`** — it crashes with a missing snapshot in this install.

## Step 2 — Widget tests

Test file location: `calai_frontend/test/`

**Behaviour facts come from `skills/flutter-dev/SKILL.md`, not from this file.** Where that spec
lists an item under "Decisions pending", there is nothing to test yet — do not invent the
expected behaviour. Say it's blocked and move on.

### What to test per widget/screen

**`status_strip.dart`** (fully specified — safe to test)
- Hero number renders correct kcal integer, colour = `zoneColor(progress)` per the thresholds
  in `flutter-dev/SKILL.md` "Zone colour signal" (< 80%, 80–100%, 100–115%, > 115%)
- Accent line fill width = `min(progress, 1.0)` × strip width; track stays `bgSurface`
- Macro row sums today's entries' `protein_g`/`carbs_g`/`fat_g` correctly
- Zero-entries state: hero reads "0", `signalGrey`, accent line fill width 0, macro row
  "P 0g · C 0g · F 0g"
- Golden test for each zone-threshold state

**`meal_input_bar.dart`**
- TextField accepts text input
- Submit fires the callback **with the typed text** (the callback must carry a `String`
  payload — a bare `VoidCallback` cannot deliver it)
- Empty / whitespace-only submit does not fire the callback
- ⛔ In-flight/loading appearance — **blocked on pending decision #5**

**`onboarding_screen.dart`** (conversational thread, not a `PageView`/form — see
`flutter-dev/SKILL.md` "Onboarding screen")
- Empty state (no messages yet): shows the headline + example body text, `MealInputBar` with
  placeholder "Tell me about yourself…"
- Submitting a message via the input bar calls `onboardingProvider.notifier.sendMessage` and
  appends a user message to the thread (plain text, no card)
- Agent messages render via `AgentMessage`, switching on `message_type`
  (`slot_fill_question` renders a plain question; `profile_confirmation` renders the
  structured card with fields + `Confirm` button)
- Tapping `Confirm` on a `profile_confirmation` message calls `userProvider.notifier.confirm`
  with the previewed profile, and on success navigates to `/home`
- New message appended → thread auto-scrolls to bottom
- No "Finish button disabled until valid" behaviour to test — there is no form; validity is
  the agent's slot-filling loop, not a client-side field check

**`home_screen.dart`** (today's diary/session screen — see `flutter-dev/SKILL.md` "Today
screen")
- Status strip renders today's entries' totals (see `status_strip.dart` above)
- Entry feed shows one `entry_card.dart` per logged submission (not one row per parsed item —
  raw text + `total_kcal`, with item chips below), oldest at top, newest appended at bottom
- Swipe-to-delete removes the correct whole entry (needs a stable id — names can collide) and
  updates the status strip total
- Input bar submission appends a `pending` entry card immediately, then transitions to
  `logged` (or `error`) once the response lands
- Tapping the "TODAY · <date>" header opens `history_sheet.dart`; tapping a past-day row swaps
  the same screen's data to that date in place (not a new route)

### Rules for widget tests
- No network. Wrap in `ProviderScope` with `overrides` supplying fake services.
- Riverpod 3: providers are `Notifier`/`AsyncNotifier`; assert on `AsyncValue` states
  (loading → data/error), not on `setState` side effects.

## Step 3 — Manual golden path

Run the app. iOS on-device debugging is currently broken (Xcode debug-session handshake
fails), so verify in Chrome:
```bash
cd calai_frontend && flutter run -d chrome
```
Use DevTools' device toolbar (⌘⇧M) at phone width to keep the layout honest.

Checklist:
- [ ] First launch → lands on onboarding
- [ ] Complete setup → `/api/calculate` called → goal stored → redirected to home
- [ ] Log a meal → `/api/parse-meal` called → entry appears in list → today's ring fills
- [ ] Swipe to delete → day total decreases
- [ ] Reload / relaunch → profile persists, today's meals still shown
- [ ] Backend stopped → error surfaces (SnackBar), typed input is not lost
- [ ] A 20–40s call → the UI is not frozen and the submit control is disabled while in flight

## Step 4 — Backend connectivity check

Ensure backend is running before integration tests:
```bash
uvicorn calai_backend.main:app --reload --host 0.0.0.0
```

Test endpoints directly:
```bash
curl -X POST http://localhost:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{"age":25,"gender":"male","weight_kg":75,"height_cm":178,"activity_level":"moderately_active","goal":"maintain","goal_rate_kg_per_week":0.5}'

curl -X POST http://localhost:8000/api/parse-meal \
  -H "Content-Type: application/json" \
  -d '{"meal_text":"2 eggs and toast","meal_type":"breakfast"}'
```

Exact field names matter — these are the ones the backend actually reads:
- `activity_level` ∈ `sedentary | lightly_active | moderately_active | very_active | extra_active`
  (**not** `"moderate"`)
- `goal_rate_kg_per_week` (**not** `rate_kg_per_week`), and it must be `> 0`
- `meal_text` (**not** `text`); `meal_type` optional, defaults to `snack`

A 422 from either call almost always means a field name or enum value is wrong, not that the
app is broken. Treat these curls as the contract regression check — if they 422, fix the caller.

## Rules
- Never mock the backend in tests that cover the API call path — use `http.MockClient` only for unit tests of `api_service.dart` in isolation
- For widget tests that involve providers, wrap in `ProviderScope` with override
- If a test fails, read the error fully before changing code — don't suppress with `try/catch`
