# Rule: frontend hard facts

- **Static analysis.** `dart analyze lib/<file>` — **never** `flutter analyze`, which crashes
  with a missing snapshot in this install.
- **Colour API.** Always `.withValues(alpha: x)` — `.withOpacity()` is deprecated. Never use
  `Colors.*` constants — always `AppColors.*` from `lib/core/app_theme.dart`.
- **Request field names.** `meal_text` not `text`; `goal_rate_kg_per_week`; the 5-value
  `activity_level` enum — match `skills/flutter-dev/SKILL.md` field-for-field.
- **Error handling.** As of the P1 fix (2026-09-14), every backend error response is one shape:
  `{"detail": {"message": <string>, "errors": <list|null>}}`. Read `detail.message` for display
  text; `detail.errors` is non-null only on 422 validation failures. Do not write "string or
  list" tolerance code — that was the pre-fix shape and is now wrong.
- **Native assets crash** (`Couldn't resolve native function 'DOBJC_initializeApi'`): fix with
  `flutter clean && flutter pub get`, not a code change.
- **Architecture layering.** Models are plain Dart, no Flutter imports. `api_service.dart` is
  HTTP-only, no state. `storage_service.dart` only wraps SharedPreferences. Providers depend on
  services, not directly on `http`/SharedPreferences. Screens only call providers.

Referenced by: `flutter-engineer.md`, `ui-engineer.md`, `skills/flutter-dev/SKILL.md`.
