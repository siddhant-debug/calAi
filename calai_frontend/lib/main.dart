import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'core/app_theme.dart' show AppTheme;
import 'providers/user_provider.dart';
import 'screens/home_screen.dart';
import 'screens/onboarding_screen.dart';

void main() => runApp(const ProviderScope(child: CalAiApp()));

/// Bridges [userProvider]'s async profile state into go_router's
/// `refreshListenable` so `/`'s redirect re-evaluates once the profile
/// finishes loading from storage, without recreating the router itself.
class _ProfileRefresh extends ChangeNotifier {
  bool? hasProfile;

  void update(bool? value) {
    if (value == hasProfile) return;
    hasProfile = value;
    notifyListeners();
  }
}

class CalAiApp extends ConsumerStatefulWidget {
  const CalAiApp({super.key});

  @override
  ConsumerState<CalAiApp> createState() => _CalAiAppState();
}

class _CalAiAppState extends ConsumerState<CalAiApp> {
  final _refresh = _ProfileRefresh();
  late final GoRouter _router = GoRouter(
    refreshListenable: _refresh,
    routes: [
      GoRoute(
        path: '/',
        redirect: (context, state) => _refresh.hasProfile == true ? '/home' : '/onboarding',
      ),
      GoRoute(path: '/onboarding', builder: (context, _) => const OnboardingScreen()),
      GoRoute(path: '/home', builder: (context, _) => const HomeScreen()),
    ],
  );

  @override
  void initState() {
    super.initState();
    ref.listenManual(userProvider, (previous, next) {
      _refresh.update(next.value != null);
    }, fireImmediately: true);
  }

  @override
  void dispose() {
    _refresh.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'calAI',
      debugShowCheckedModeBanner: false,
      theme: AppTheme.darkTheme,
      routerConfig: _router,
    );
  }
}
