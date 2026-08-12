---
name: flutter-test
description: Test the calAI Flutter frontend — widget tests, integration checks, and manual golden-path verification. Use when the user says "test", "write tests", "check if it works", "does the ring render", "test onboarding", "verify the meal input", or asks to validate any Flutter feature. Also trigger on "run the app", "check on simulator", or "does X work on device".
---

# calAI Flutter Test Skill

You are testing the calAI Flutter iOS frontend. Always read `archdocs/frontendidea.md` first to understand expected behaviour before writing or running any test.

## Project location
`calai_frontend/` — run all commands from inside this directory.

## Step 1 — Static analysis first
Always run before anything else:
```bash
cd calai_frontend && flutter analyze
```
Fix all errors and warnings before proceeding.

## Step 2 — Widget tests

Test file location: `calai_frontend/test/`

### What to test per widget/screen

**`day_ring.dart`**
- Renders without error at 0%, 80%, 100%, 115%, 150% fill
- Correct colour: grey / green / amber / red at each threshold
- Center text shows correct kcal integer

**`meal_input_bar.dart`**
- TextField accepts text input
- Submit button triggers callback with correct string
- Loading state: button replaced with spinner
- Empty submit does not fire callback

**`onboarding_screen.dart`**
- All 4 pages navigate forward on tap
- Cannot swipe back (forward-only PageView)
- Finish button disabled until all fields valid
- On valid Finish: calls `POST /api/calculate` with correct body shape

**`home_screen.dart`**
- Meal list shows today's entries
- Swipe-to-delete removes entry and updates ring total
- Input bar submission appends new entry
- 5 rings render for Mon–Fri of current ISO week

## Step 3 — Manual golden path (simulator)

Run the app:
```bash
cd calai_frontend && flutter run
```

Checklist:
- [ ] First launch → lands on onboarding
- [ ] Complete all 4 steps → `/api/calculate` called → stored in SharedPreferences → redirected to home
- [ ] Log a meal → `/api/parse-meal` called → entry appears in list → today's ring fills
- [ ] Swipe to delete → ring total decreases
- [ ] Kill and relaunch → lands on home (profile persists), meals for today still shown
- [ ] All 5 Mon–Fri rings visible with correct colour coding

## Step 4 — Backend connectivity check

Ensure backend is running before integration tests:
```bash
uvicorn calai_backend.main:app --reload --host 0.0.0.0
```

Test endpoints directly:
```bash
curl -X POST http://localhost:8000/api/calculate \
  -H "Content-Type: application/json" \
  -d '{"age":25,"gender":"male","weight_kg":75,"height_cm":178,"activity_level":"moderate","goal":"maintain","rate_kg_per_week":0}'

curl -X POST http://localhost:8000/api/parse-meal \
  -H "Content-Type: application/json" \
  -d '{"text":"2 eggs and toast"}'
```

## Rules
- Never mock the backend in tests that cover the API call path — use `http.MockClient` only for unit tests of `api_service.dart` in isolation
- For widget tests that involve providers, wrap in `ProviderScope` with override
- If a test fails, read the error fully before changing code — don't suppress with `try/catch`
