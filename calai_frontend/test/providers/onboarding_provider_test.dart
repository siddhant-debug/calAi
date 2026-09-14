// Coverage for ADR-008's frontend half: OnboardingNotifier.sendMessage's
// conversation-history accumulation (providers/user_provider.dart). The
// original bug (ADR-008) was cross-turn state loss — the agent re-asked for
// fields already given because no prior-turn context was ever resent. These
// tests make >=2 sequential sendMessage calls and assert what the *second*
// (and third) call actually sends as conversationHistory, per tester.md's
// DoD requirement for conversational/agentic flow coverage. No network, no
// API key — FakeApiService stubs ApiService.agent entirely.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'package:calai_frontend/models/agent_response.dart';
import 'package:calai_frontend/providers/user_provider.dart';

import '../support/fake_api_service.dart';

void main() {
  AgentResponse infoResponse(String text) => AgentResponse(response: text, iterationsUsed: 1);

  test('first sendMessage call sends no conversation history', () async {
    final fakeApi = FakeApiService(agentResponse: infoResponse('ok'));
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    final notifier = container.read(onboardingProvider.notifier);
    await notifier.sendMessage('I am 30, male, 80kg, 180cm');

    expect(fakeApi.agentCallCount, 1);
    expect(fakeApi.lastConversationHistory, isNull);
  });

  test('second sendMessage call sends exactly the first message as history, '
      'not the current message and not any agent response text', () async {
    final fakeApi = FakeApiService(agentResponse: infoResponse('what is your goal?'));
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    final notifier = container.read(onboardingProvider.notifier);

    await notifier.sendMessage('I am 30, male, 80kg, 180cm');
    expect(fakeApi.lastConversationHistory, isNull);

    fakeApi.agentResponse = infoResponse('great, all set');
    await notifier.sendMessage('moderately active, want to lose weight');

    expect(fakeApi.agentCallCount, 2);
    expect(fakeApi.lastConversationHistory, ['I am 30, male, 80kg, 180cm']);
  });

  test('third sendMessage call sends both prior user messages, oldest first '
      '— guards against reintroducing the cross-turn state-loss bug', () async {
    final fakeApi = FakeApiService(agentResponse: infoResponse('what is your goal?'));
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    final notifier = container.read(onboardingProvider.notifier);

    await notifier.sendMessage('I am 30, male, 80kg, 180cm');

    fakeApi.agentResponse = infoResponse('anything else?');
    await notifier.sendMessage('moderately active, want to lose weight');

    fakeApi.agentResponse = infoResponse('all set, confirm?');
    await notifier.sendMessage('yes confirm');

    expect(fakeApi.agentCallCount, 3);
    expect(
      fakeApi.lastConversationHistory,
      [
        'I am 30, male, 80kg, 180cm',
        'moderately active, want to lose weight',
      ],
      reason: 'must be oldest-first and exclude the current message + all agent text',
    );
  });
}
