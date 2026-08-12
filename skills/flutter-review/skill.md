---
name: flutter-review
description: Review calAI Flutter frontend code for correctness, simplicity, and architecture fit. Use when the user says "review", "check my code", "is this right", "look at the widget", "review the screen", "code review", or "is this good Flutter". Also trigger after a screen is implemented and user wants a second opinion before moving on.
---

# calAI Flutter Review Skill

You are reviewing the calAI Flutter iOS frontend. Read `archdocs/frontendidea.md` before reviewing any file — it is the source of truth for intended behaviour, not what the code currently does.

## Step 1 — Read the file in full
Use the Read tool on the target file. Never review from memory or partial context.

## Step 2 — Run static analysis
```bash
cd calai_frontend && flutter analyze lib/<file>
```
Report all issues found, even if the user didn't ask about them.

## Step 3 — Review checklist

### Correctness
- [ ] API request body matches backend expectations (`/api/calculate`, `/api/parse-meal`)
- [ ] SharedPreferences keys match exactly: `"user_profile"`, `"calorie_goal"`, `"meals_YYYY-MM-DD"`
- [ ] Weekly totals load Mon–Fri of current ISO week (not last 7 days)
- [ ] Ring fill clamped to `[0.0, 1.0]` before painting
- [ ] Colour thresholds: grey <0.80, green 0.80–1.00, amber 1.00–1.15, red >1.15
- [ ] go_router redirect logic: no profile → `/onboarding`, has profile → `/home` (never back to onboarding after finish)
- [ ] Onboarding PageView is forward-only (no back navigation)
- [ ] Swipe-to-delete updates provider state AND SharedPreferences

### Simplicity
- [ ] No unnecessary abstraction — three similar lines is fine
- [ ] No error handling for impossible cases (trust Riverpod, trust SharedPreferences)
- [ ] No comments that explain WHAT the code does (only WHY if non-obvious)
- [ ] Widgets are not over-extracted — each file has one clear responsibility

### Flutter conventions
- [ ] `const` constructors used where possible
- [ ] `AnimationController` disposed in `dispose()`
- [ ] No `setState` inside Riverpod-managed screens (use `ref.read` / `ref.watch`)
- [ ] `CustomPainter` `shouldRepaint` returns `true` only when the painted value changes
- [ ] `ListView` items have a `key` (for swipe-to-delete stability)

### Architecture fit
- [ ] Models are plain Dart — no Flutter imports
- [ ] `api_service.dart` only does HTTP — no state, no SharedPreferences
- [ ] `storage_service.dart` only wraps SharedPreferences — no HTTP
- [ ] Providers depend on services, not directly on `http` or SharedPreferences
- [ ] Screens only call providers — no direct service calls from screen widgets

## Step 4 — Report format

Summarise findings in three buckets:
1. **Bugs / correctness issues** — must fix before moving on
2. **Simplification** — optional but recommended
3. **Looks good** — what is well done (important for morale, note non-obvious wins)

Be direct. One finding per bullet. No fluff.
