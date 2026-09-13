import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_service.dart';
import '../core/storage_service.dart';
import '../models/agent_response.dart';
import '../models/conversation_message.dart';
import '../models/calc_response.dart';
import '../models/user_profile.dart';

final apiServiceProvider = Provider<ApiService>((ref) => const ApiService());

final storageServiceProvider = Provider<StorageService>((ref) => StorageService());

/// The confirmed profile, loaded from client-side storage (ADR-007 Part 3).
/// Null before onboarding's confirm step has ever completed.
final userProvider = AsyncNotifierProvider<UserNotifier, UserProfile?>(UserNotifier.new);

class UserNotifier extends AsyncNotifier<UserProfile?> {
  @override
  Future<UserProfile?> build() {
    return ref.read(storageServiceProvider).loadProfile();
  }

  /// Locks the profile in: validates it against `/api/calculate`, then
  /// persists it. Fires from onboarding's Confirm button.
  Future<void> confirm(UserProfile profile) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() async {
      await ref.read(apiServiceProvider).calculate(profile);
      await ref.read(storageServiceProvider).saveProfile(profile);
      return profile;
    });
  }

  Future<void> clear() async {
    await ref.read(storageServiceProvider).clearProfile();
    state = const AsyncValue.data(null);
  }
}

/// The confirmed profile's daily calorie goal — derived, not stored,
/// per ADR-007 (`CalcResponse` is a computed preview, not persisted state).
final calorieGoalProvider = FutureProvider<CalcResponse?>((ref) async {
  final profile = await ref.watch(userProvider.future);
  if (profile == null || !profile.isComplete) return null;
  return ref.read(apiServiceProvider).calculate(profile);
});

/// The onboarding conversational thread. Session-scoped to the onboarding
/// screen's lifetime — not persisted, since the only durable output of
/// onboarding is the confirmed `UserProfile` handled by [UserNotifier].
final onboardingProvider =
    AsyncNotifierProvider<OnboardingNotifier, List<ConversationMessage>>(OnboardingNotifier.new);

class OnboardingNotifier extends AsyncNotifier<List<ConversationMessage>> {
  @override
  Future<List<ConversationMessage>> build() async => [];

  Future<void> sendMessage(String text) async {
    final current = state.value ?? [];
    final withUserMessage = [...current, ConversationMessage.user(text)];
    state = AsyncValue.data(withUserMessage);

    try {
      final response = await ref.read(apiServiceProvider).agent(text);
      state = AsyncValue.data([...withUserMessage, ConversationMessage.agent(response)]);
    } catch (e) {
      final fallback = AgentResponse(
        response: "Couldn't reach the server — try again in a moment.",
        iterationsUsed: 0,
      );
      state = AsyncValue.data([...withUserMessage, ConversationMessage.agent(fallback)]);
    }
  }
}
