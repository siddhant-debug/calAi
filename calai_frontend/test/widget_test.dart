// Smoke test for CalAiApp's real startup/redirect behavior, rewritten
// against the post-ADR-007 rebuild (flutter-engineer's P2). The previous
// version of this file asserted on the old HomeScreen's exact ListTile-
// based structure, which no longer exists.
//
// While writing this rewrite, pumping the real CalAiApp end-to-end (go_router
// redirect included) with a profile already in storage surfaced a NEW,
// previously-unknown bug — see the second test below. Because of that bug,
// the app never actually reaches '/home' via the router in this scenario,
// so the Material/ListTile-ancestor crash regression (the thing this file
// was specifically asked to prove) is instead verified by rendering
// HomeScreen directly (third test) with the exact same stored-profile state
// the router would hand it — this is a deliberate, documented workaround,
// not a downgrade of the assertion: it still pumps the real HomeScreen
// widget tree and asserts zero FlutterErrors, not "doesn't use ListTile" by
// inspection.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:calai_frontend/main.dart';
import 'package:calai_frontend/models/calc_response.dart';
import 'package:calai_frontend/providers/user_provider.dart';
import 'package:calai_frontend/screens/home_screen.dart';

import 'support/fake_api_service.dart';

const _storedProfileJson = '{"weight_kg":70,"height_cm":175,"age":28,"gender":"male",'
    '"activity_level":"moderately_active","goal":"maintain","goal_rate_kg_per_week":0.5}';

void main() {
  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('CalAiApp redirects to onboarding when no profile is stored', (tester) async {
    await tester.pumpWidget(
      ProviderScope(
        overrides: [apiServiceProvider.overrideWithValue(FakeApiService())],
        child: const CalAiApp(),
      ),
    );
    await tester.pumpAndSettle();

    // OnboardingScreen's empty-state copy.
    expect(find.text('Tell me about yourself and your goal.'), findsOneWidget);
    // Home screen's entries label must NOT be present.
    expect(find.text('ENTRIES'), findsNothing);
  });

  testWidgets(
    'BUG (found while rewriting this test, not fixed here — tester does not own lib/): '
    "CalAiApp does not navigate to '/home' when a profile is already stored at startup; "
    "it stays on '/onboarding' indefinitely",
    (tester) async {
      SharedPreferences.setMockInitialValues({'profile': _storedProfileJson});

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiServiceProvider.overrideWithValue(
              FakeApiService(
                calcResponse: const CalcResponse(bmrKcal: 1600, tdeeKcal: 2200, calorieGoalKcal: 2000),
              ),
            ),
          ],
          child: const CalAiApp(),
        ),
      );
      await tester.pumpAndSettle();

      // Likely mechanism (see main.dart's `_ProfileRefresh`/redirect):
      // `ref.listenManual(userProvider, ..., fireImmediately: true)` reports
      // hasProfile == false the instant userProvider is still AsyncLoading,
      // so the '/' route's redirect commits to '/onboarding' before the
      // (inherently async) SharedPreferences read finishes. Once it
      // finishes and `_refresh.update(true)` fires `notifyListeners()`,
      // go_router's `refreshListenable` re-parses the CURRENT location
      // ('/onboarding', which has no redirect of its own) rather than '/'
      // again, so it never reaches '/home'. This documents the ACTUAL
      // (buggy) current behavior — expected/correct behavior is landing on
      // '/home' — flagged to flutter-engineer via this unit's report, not
      // silently left uncovered.
      expect(
        find.text('Tell me about yourself and your goal.'),
        findsOneWidget,
        reason: 'documents current behavior; update this test once the redirect race is fixed',
      );
      expect(find.text('ENTRIES'), findsNothing);
    },
  );

  testWidgets(
    'HomeScreen renders without any FlutterError given a stored profile '
    '(Material/ListTile-ancestor crash regression)',
    (tester) async {
      SharedPreferences.setMockInitialValues({'profile': _storedProfileJson});

      final caughtErrors = <FlutterErrorDetails>[];
      final originalOnError = FlutterError.onError;
      FlutterError.onError = (details) => caughtErrors.add(details);

      await tester.pumpWidget(
        ProviderScope(
          overrides: [
            apiServiceProvider.overrideWithValue(
              FakeApiService(
                calcResponse: const CalcResponse(bmrKcal: 1600, tdeeKcal: 2200, calorieGoalKcal: 2000),
              ),
            ),
          ],
          child: const MaterialApp(home: HomeScreen()),
        ),
      );
      await tester.pumpAndSettle();

      FlutterError.onError = originalOnError;

      // The regression assertion this file was specifically asked to add:
      // the old HomeScreen wrapped each ListTile in a Container with no
      // Material ancestor and raised a FlutterError on every build. The new
      // home_screen.dart doesn't use ListTile at all — confirmed here by
      // actually pumping it and asserting zero FlutterErrors of any kind,
      // not just the previously-tolerated ListTile one.
      expect(
        caughtErrors,
        isEmpty,
        reason: 'home_screen.dart must render without raising any FlutterError. Caught: '
            '${caughtErrors.map((d) => d.exceptionAsString()).toList()}',
      );

      expect(find.text('ENTRIES'), findsOneWidget);
      expect(find.text('Nothing logged yet.'), findsOneWidget);
    },
  );
}
