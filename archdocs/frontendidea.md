# calAI Flutter Frontend — superseded

This document (ring-and-streak dashboard, 4-step form onboarding, 5 Mon–Fri day rings) is
**superseded** as of 2026-09-13. It is kept only as a historical record of the original idea;
do not implement against it.

Current product direction: **`plans/v1-product-brief.md`** — calAI as a quiet, per-day food
diary. Read it first.

Current UI/UX spec: **`skills/flutter-dev/SKILL.md`**, "Design system" section — Onboarding
screen (conversational), Today screen (diary session), Status strip, Entry feed & Entry card,
History sheet. This is the single source of truth for tokens, layout, and interaction; do not
fork or duplicate it here.

What changed, briefly: no ring, no streaks, no badges, no weekly ring row, no 4-step form. Each
day is a separate session (like a fresh chat thread for that date). Logging a meal is silent —
the entry is the feedback, no agent reply. The only thing the app says unprompted is a weekly
weight check-in question. Onboarding is one free-text message, extracted into a profile, one
confirm step. See the brief's "Problem" and "In scope" sections for the full reasoning, and the
skill file for the exact screen specs.

## Original idea (historical, do not build)

Full screen to write and then extract calories. Once logged, a circle for that particular day
shows progress. Connect with Apple Health to track fitness / workouts.

The original plan below (4-step onboarding `PageView`, 5 Mon–Fri day rings, SharedPreferences
keys `user_profile`/`calorie_goal`/`meals_YYYY-MM-DD`) is retired in full. It is not reproduced
here — see git history for this file (pre-2026-09-13) if the original text is needed for
reference.
