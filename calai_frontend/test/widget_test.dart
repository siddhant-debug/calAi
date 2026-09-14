// Smoke test for CalAiApp's real startup/redirect behavior, rewritten
// against the post-ADR-007 rebuild (flutter-engineer's P2). The previous
// version of this file asserted on the old HomeScreen's exact ListTile-
// based structure, which no longer exists.
//
// While writing this rewrite, pumping the real CalAiApp end-to-end (go_router
// redirect included) with a profile already in storage surfaced a redirect
// race: the '/' route's own redirect committed to '/onboarding' before the
// async SharedPreferences read resolved, and go_router's refreshListenable
// then re-evaluated the current ('/onboarding') route rather than '/' again,
// so '/home' was never reached. Fixed in main.dart by moving the redirect to
// a top-level `redirect:` on GoRouter itself, re-evaluated on every
// refreshListenable notification regardless of current location — see the
// second test below, now asserting the correct ('/home') outcome. The
// Material/ListTile-ancestor crash regression (the thing this file was
// specifically asked to prove) is still additionally verified by rendering
// HomeScreen directly (third test) with the exact same stored-profile state
// the router would hand it.

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
    'CalAiApp navigates to \'/home\' when a profile is already stored at startup '
    '(regression test for the redirect race fixed in main.dart: the router now uses a '
    "top-level `redirect:` re-evaluated on every refreshListenable notification, instead "
    "of a per-route redirect on '/' only)",
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

      expect(find.text('ENTRIES'), findsOneWidget);
      expect(find.text('Tell me about yourself and your goal.'), findsNothing);
    },
  );

  testWidgets(
    'CalAiApp with a stored profile shows onboarding on the very first frame '
    '(profile load is still pending) and only reaches /home once the async '
    'SharedPreferences read resolves and refreshListenable re-fires — this is '
    'the exact race from the original bug: the first frame commits to '
    "'/onboarding' before hasProfile is known, and the fix must re-evaluate "
    "the redirect against the CURRENT location (not just '/') once it is.",
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

      // No further pump yet: userProvider's build() is an in-flight Future
      // (SharedPreferences.getInstance() has not resolved), so hasProfile is
      // still null and the '/' route's own redirect has already committed to
      // '/onboarding' for this frame. If this assertion ever fails because
      // the app skips straight to '/home', the async load is no longer
      // actually async in this scenario and the rest of this test is moot —
      // but it currently does reproduce the pending state.
      expect(find.text('Tell me about yourself and your goal.'), findsOneWidget);
      expect(find.text('ENTRIES'), findsNothing);

      // Let the SharedPreferences future resolve and refreshListenable fire.
      await tester.pumpAndSettle();

      // The fix: redirect re-evaluated against the CURRENT location
      // ('/onboarding', not '/'), so it now correctly lands on '/home'.
      expect(find.text('ENTRIES'), findsOneWidget);
      expect(find.text('Tell me about yourself and your goal.'), findsNothing);
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
