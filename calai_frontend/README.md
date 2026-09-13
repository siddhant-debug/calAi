# CalAI — Flutter Frontend

The mobile/web client for CalAI. **Current state: a visual mockup, not a working app** — worth knowing before you dig in.

## What's actually wired up vs. stubbed

| File | Status |
|---|---|
| `lib/core/app_theme.dart` | Real — design tokens (colors, spacing, type scale) |
| `lib/screens/home_screen.dart` | Real UI, **hardcoded fake data** (3 fixed meals, 5 fixed day-rings) — no backend call |
| `lib/widgets/day_ring.dart`, `lib/widgets/meal_input_bar.dart` | Real, presentational |
| `lib/core/api_service.dart` | **Empty stub** (0 lines) — no HTTP client to the backend yet |
| `lib/core/storage_service.dart` | **Empty stub** — no persistence |
| `lib/models/meal_entry.dart`, `lib/models/user_profile.dart` | **Empty stubs** — no data models |
| `lib/providers/meal_provider.dart`, `lib/providers/user_provider.dart` | **Empty stubs** — no Riverpod state wiring |
| `lib/screens/onboarding_screen.dart` | **Empty stub** — no onboarding flow |

So: `flutter run` shows a real-looking screen, but tapping "log a meal" does nothing persistent, and nothing here talks to `calai_backend`'s `/api/agent` or `/api/parse-meal` yet. See the root `README.md`'s "How we're improving" section for what the backend side already does — the gap is purely on this side of the wire.

## Running it

```bash
cd calai_frontend
flutter pub get
flutter devices        # confirm your target shows up
flutter run -d <device-id>
```

### Running on a physical iPhone

Two one-time setup steps that aren't Flutter-specific:

1. **Trust the developer certificate** on the phone if this is its first time running a locally-signed build (Settings → General → VPN & Device Management).
2. **Xcode needs the matching iOS platform-support files** for your phone's exact iOS version — if `flutter run` fails with `iOS <version> is not installed`, this can't be fixed from the CLI reliably (`xcodebuild -downloadPlatform iOS` can silently stall waiting on an interactive license/auth prompt with no visible progress). Do it from **Xcode → Settings → Components** instead, where you get a real progress bar.

Run `flutter doctor` first regardless — it should show a clean iOS/Android/web toolchain with your device listed under "Connected device."

## Design system

`skills/flutter-dev/SKILL.md` (project root) is the single source of truth for the visual spec — tokens, layout conventions, `AppColors.*` usage. Run `dart analyze lib/<file>` (not `flutter analyze`) to check a file against project conventions.

## Next steps (see root README's ownership table for who owns what)

The empty stub files above are the actual remaining scope — wiring `api_service.dart` to the backend, adding real state via the provider stubs, and building the onboarding flow are all separate units of work, not yet started.
