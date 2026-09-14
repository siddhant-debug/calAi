# CalAI — Flutter Frontend

The mobile client for CalAI — a notebook-style food diary, not a dashboard. It talks to
`calai_backend` for real: conversational onboarding through `/api/agent`, meal logging through
`/api/parse-meal`, with results persisted locally via `SharedPreferences`.

## What it does

- **Onboarding** is a conversation, not a form. You describe yourself in free text; the agent
  extracts a profile across however many turns it takes, then shows a confirmation card with the
  computed daily calorie target.
- **The diary** is the home screen: type what you ate, the entry appears immediately as
  `pending`, then resolves to `logged` with per-item calories and macros once the backend
  answers. The status strip's total, macros and progress fill update live.
- **History** is a bottom sheet reached from the day header — a per-day total for the last 30
  days, plus the latest recorded weight.

All 14 spec files are implemented (see `skills/flutter-dev/SKILL.md` for the spec they're built
against). Backend calls run through `lib/core/api_service.dart`; local persistence through
`lib/core/storage_service.dart`; state through Riverpod providers in `lib/providers/`.

**One caveat worth knowing before you run it:** every meal-parse and onboarding message is a real
LLM call taking roughly 8–25 seconds. The pending state you see is the app waiting on the model,
not a hang.

## Running it

```bash
cd calai_frontend
flutter pub get
flutter devices        # confirm your target shows up
flutter run -d <device-id>
```

The backend must be running, or every call fails with a "couldn't reach the server" message.
From the repo root:

```bash
python3 -m uvicorn calai_backend.main:app --host 0.0.0.0 --port 8000
```

`ApiService.baseUrl` defaults to `http://localhost:8000/api`, which works as-is on the **iOS
Simulator** (it shares the host Mac's network stack). A **physical device** is a different
machine on the network and needs your Mac's LAN IP instead — change the default in
`lib/core/api_service.dart`. Note that nothing in the test suite exercises this value (tests
inject a fake API service), so a wrong one fails only at runtime.

### Running on a physical iPhone

Two one-time setup steps that aren't Flutter-specific:

1. **Trust the developer certificate** on the phone if this is its first time running a locally-signed build (Settings → General → VPN & Device Management).
2. **Xcode needs the matching iOS platform-support files** for your phone's exact iOS version — if `flutter run` fails with `iOS <version> is not installed`, this can't be fixed from the CLI reliably (`xcodebuild -downloadPlatform iOS` can silently stall waiting on an interactive license/auth prompt with no visible progress). Do it from **Xcode → Settings → Components** instead, where you get a real progress bar.

Run `flutter doctor` first regardless — it should show a clean iOS/Android/web toolchain with your device listed under "Connected device."

## Design system

`skills/flutter-dev/SKILL.md` (project root) is the single source of truth for the visual spec — tokens, layout conventions, `AppColors.*` usage. Run `dart analyze lib/<file>` (not `flutter analyze`) to check a file against project conventions.

## Tests

```bash
flutter test           # 28 tests: providers, services, widgets
dart analyze lib       # never `flutter analyze` — it crashes in this install
```

Green tests are necessary but not sufficient here — see `rules/gates.md` for the three bug
classes the suite structurally cannot catch (config behind a faked boundary, behaviour spanning
multiple calls, and cache staleness). Both real bugs found on 2026-09-14 were found by running
the app, each after a clean review on green gates. Drive the real flow before calling UI work
done.
