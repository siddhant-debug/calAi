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

**`day_ring.dart`** (fully specified — safe to test)
- Renders without error at 0%, 80%, 100%, 115%, 150% fill
- Correct colour per the thresholds in `flutter-dev/SKILL.md` "Day ring colour logic"
- Center text shows correct kcal integer
- Golden test for each of the above states

**`meal_input_bar.dart`**
- TextField accepts text input
- Submit fires the callback **with the typed text** (the callback must carry a `String`
  payload — a bare `VoidCallback` cannot deliver it)
- Empty / whitespace-only submit does not fire the callback
- ⛔ In-flight/loading appearance — **blocked on pending decision #5**

**`onboarding_screen.dart`**
- Finish button disabled until all fields valid
- On valid Finish: calls `POST /api/calculate` with the exact body shape in Step 4
- ⛔ Page count, forward-only behaviour and step grouping — **not final** (`frontendidea.md`
  is a sketch); test only what the spec states once it's settled

**`home_screen.dart`**
- Meal list shows today's entries
- Swipe-to-delete removes the correct entry (needs a stable id — names can collide) and
  updates the day total
- Input bar submission appends an entry
- ⛔ Ring count / week window — **blocked on pending decision #3**
- ⛔ One row per submission vs per item — **blocked on pending decision #1**

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
