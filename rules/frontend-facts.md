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
- **API base URL.** `ApiService.baseUrl` defaults to `http://localhost:8000/api`. The iOS
  Simulator shares the host Mac's network stack, so `localhost` reaches a locally-run backend
  directly; a **physical device** needs the Mac's LAN IP instead. This default is never
  exercised by the test suite (tests inject `FakeApiService`), so a wrong value here fails only
  at runtime — it shipped once as a literal unfilled `<LOCAL_IP>` placeholder behind a fully
  green suite.
- **Provider cache invalidation.** A provider that caches a derived read of storage must be
  invalidated by every provider that writes that storage. Riverpod's `AsyncNotifierProvider`
  runs `build()` once and caches; `ref.read(p.future)` returns the cached future and does **not**
  rebuild. Concretely: any write path in `meal_provider.dart` that touches `storageServiceProvider`
  must `ref.invalidate(historyProvider)` after the write succeeds (not before — invalidating
  ahead of the write just re-caches stale data). Adding a new mutation path without this is a
  correctness bug, not a nitpick: the history sheet silently served a pre-write total until it
  was caught by hand on 2026-09-14.

Referenced by: `flutter-engineer.md`, `ui-engineer.md`, `skills/flutter-dev/SKILL.md`.
