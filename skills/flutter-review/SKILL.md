---
name: flutter-review
description: Review calAI Flutter frontend code for correctness, simplicity, and architecture fit. Use when the user says "review", "check my code", "is this right", "look at the widget", "review the screen", "code review", or "is this good Flutter". Also trigger after a screen is implemented and user wants a second opinion before moving on.
---

# calAI Flutter Review Skill

You are reviewing the calAI Flutter frontend. Read `skills/flutter-dev/SKILL.md` before
reviewing any file — **that** is the source of truth for intended behaviour and design, not
what the code currently does.

`archdocs/frontendidea.md` is background product intent and is **not final** — treat it as
context, never as a spec to review against. Where the two differ, `flutter-dev/SKILL.md` wins;
where `flutter-dev/SKILL.md` marks something "Decisions pending", there is no correct
behaviour yet and implementing one is itself a finding.

## Step 1 — Read the file in full
Use the Read tool on the target file. Never review from memory or partial context.

## Step 2 — Run static analysis
```bash
cd calai_frontend && dart analyze lib/<file>
```
(**Never `flutter analyze`** — it crashes with a missing snapshot in this install.)
Report all issues found, even if the user didn't ask about them.

## Step 3 — Review checklist

### Correctness
- [ ] `POST /api/parse-meal` body uses **`meal_text`** (not `text`), optional `meal_type`
- [ ] `POST /api/calculate` uses `activity_level` from the 5-value enum (`moderately_active`,
      not `moderate`) and `goal_rate_kg_per_week` (not `rate_kg_per_week`), value `> 0`
- [ ] Error handling reads the backend's normalized error envelope (fixed 2026-09-14): every
      error response is `{"detail": {"message": <string>, "errors": <list|null>}}` — read
      `detail.message` for display text, `detail.errors` (non-null only on 422 validation
      failures) for field-level detail. A bare `detail as String` cast is a bug against this
      shape; so is code still branching on "string vs list" for `detail` itself
- [ ] Storage keys match the spec exactly, if the client-side storage option is in force
      (persistence is an open decision — see `flutter-dev/SKILL.md` "Decisions pending")
- [ ] Ring fill clamped to `[0.0, 1.0]` before painting
- [ ] Colour thresholds match `flutter-dev/SKILL.md` "Day ring colour logic" — read them there,
      don't trust this list if the two disagree
- [ ] Ring range / week window matches the spec **once decision #3 is resolved** — flag as
      blocked, don't assume Mon–Fri
- [ ] go_router redirect: no profile → onboarding, has profile → home, never back after finish
- [ ] Swipe-to-delete updates provider state AND storage, and targets a **stable id** —
      keying by meal name collides on duplicates
- [ ] Nothing implements an item listed under "Decisions pending" in `flutter-dev/SKILL.md`

### Simplicity
- [ ] No unnecessary abstraction — three similar lines is fine
- [ ] No error handling for impossible cases (trust Riverpod, trust SharedPreferences)
- [ ] No comments that explain WHAT the code does (only WHY if non-obvious)
- [ ] Widgets are not over-extracted — each file has one clear responsibility

### Flutter conventions
- [ ] `const` constructors used where possible
- [ ] `AnimationController` disposed in `dispose()`
- [ ] No `setState` inside Riverpod-managed screens (use `ref.read` / `ref.watch`)
- [ ] Riverpod **3** API: `Notifier`/`AsyncNotifier`, not `StateNotifierProvider`; loading and
      error surfaced via `AsyncValue` (mandatory — calls take 9–40s)
- [ ] `.withValues(alpha: x)` everywhere; no `.withOpacity()`
- [ ] No `Colors.*` constants — `AppColors.*` only
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
