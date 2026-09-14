// Coverage for MealSessionNotifier's pending -> logged / pending -> error
// state transitions (providers/meal_provider.dart), per ADR-007's MealEntry
// status model. Uses a fake ApiService (no test dependency added, matches
// the codebase's plain-class convention) and mocked SharedPreferences —
// no network, no API key.

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:calai_frontend/core/api_service.dart';
import 'package:calai_frontend/models/meal_entry.dart';
import 'package:calai_frontend/providers/history_provider.dart';
import 'package:calai_frontend/providers/meal_provider.dart';
import 'package:calai_frontend/providers/user_provider.dart';

import '../support/fake_api_service.dart';

void main() {
  final date = DateTime(2026, 9, 14);

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  test('submitMeal sets a pending entry immediately, then transitions to logged '
      'on a successful /api/parse-meal response', () async {
    final fakeApi = FakeApiService(
      parseMealResult: const MealParseResult(
        items: [
          MealItem(
            name: 'egg',
            quantity: 2,
            unit: 'piece',
            caloriesKcal: 140,
            proteinG: 12,
            carbsG: 1,
            fatG: 10,
          ),
        ],
        totalKcal: 140,
        mealType: 'breakfast',
        modelLatencyMs: 500,
      ),
    );
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    // Let the initial (empty) entries load settle.
    await container.read(mealSessionProvider(date).future);

    final notifier = container.read(mealSessionProvider(date).notifier);
    final resolved = notifier.submitMeal('2 eggs and toast');

    // Synchronous portion of submitMeal runs before the first await, so the
    // pending entry is already visible without awaiting the future.
    final pendingState = container.read(mealSessionProvider(date)).value!;
    expect(pendingState, hasLength(1));
    expect(pendingState.single.status, EntryStatus.pending);
    expect(pendingState.single.rawText, '2 eggs and toast');
    expect(pendingState.single.items, isEmpty);

    await resolved;

    final loggedState = container.read(mealSessionProvider(date)).value!;
    expect(loggedState, hasLength(1));
    final entry = loggedState.single;
    expect(entry.status, EntryStatus.logged);
    expect(entry.id, pendingState.single.id, reason: 'same card must update in place');
    expect(entry.totalKcal, 140);
    expect(entry.mealType, 'breakfast');
    expect(entry.items, hasLength(1));
    expect(entry.items.single.name, 'egg');
    expect(fakeApi.parseMealCallCount, 1);
  });

  test('submitMeal transitions pending -> error when /api/parse-meal fails', () async {
    final fakeApi = FakeApiService(
      parseMealException: const ApiException(500, 'model timed out'),
    );
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    await container.read(mealSessionProvider(date).future);

    final notifier = container.read(mealSessionProvider(date).notifier);
    await notifier.submitMeal('mystery goo');

    final state = container.read(mealSessionProvider(date)).value!;
    expect(state, hasLength(1));
    final entry = state.single;
    expect(entry.status, EntryStatus.error);
    expect(entry.errorMessage, "Couldn't log — tap to retry");
    expect(entry.rawText, 'mystery goo');
  });

  test('retry re-resolves an error entry back to logged on success', () async {
    final failingApi = FakeApiService(
      parseMealException: const ApiException(500, 'model timed out'),
    );
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(failingApi)],
    );
    addTearDown(container.dispose);

    await container.read(mealSessionProvider(date).future);
    final notifier = container.read(mealSessionProvider(date).notifier);
    await notifier.submitMeal('2 eggs');

    final erroredEntry = container.read(mealSessionProvider(date)).value!.single;
    expect(erroredEntry.status, EntryStatus.error);

    // Flip the fake to succeed for the retry attempt.
    failingApi.parseMealException = null;
    failingApi.parseMealResult = const MealParseResult(
      items: [],
      totalKcal: 90,
      mealType: 'snack',
      modelLatencyMs: 300,
    );

    await notifier.retry(erroredEntry.id);

    final finalState = container.read(mealSessionProvider(date)).value!.single;
    expect(finalState.id, erroredEntry.id, reason: 'same card must update in place across retry');
    expect(finalState.status, EntryStatus.logged);
    expect(finalState.totalKcal, 90);
  });

  test('submitMeal invalidates the cached historyProvider so today\'s total '
      'reflects the newly logged entry (regression for the stale-history bug '
      'where the history sheet kept showing pre-mutation totals)', () async {
    final fakeApi = FakeApiService(
      parseMealResult: const MealParseResult(
        items: [],
        totalKcal: 245,
        mealType: 'lunch',
        modelLatencyMs: 300,
      ),
    );
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    // Force historyProvider into Riverpod's cached state BEFORE any meal is
    // logged — this is the step that reproduces the original bug. Without
    // this prior read, a first-ever read would naturally be fresh and the
    // test wouldn't catch a missing invalidate().
    final beforeHistory = await container.read(historyProvider.future);
    final beforeToday = beforeHistory.days.where((d) => d.date == date);
    final beforeTotal = beforeToday.isEmpty ? 0.0 : beforeToday.single.totalKcal;

    await container.read(mealSessionProvider(date).future);
    final notifier = container.read(mealSessionProvider(date).notifier);
    await notifier.submitMeal('chicken salad');

    final loggedState = container.read(mealSessionProvider(date)).value!.single;
    expect(loggedState.status, EntryStatus.logged);

    final afterHistory = await container.read(historyProvider.future);
    final afterToday = afterHistory.days.singleWhere((d) => d.date == date);
    expect(
      afterToday.totalKcal,
      beforeTotal + 245,
      reason: 'historyProvider must be invalidated after appendEntry so the '
          'cached AsyncNotifier state is not stale',
    );
  });

  test('deleteEntry invalidates the cached historyProvider so a deleted '
      'entry\'s kcal is no longer counted', () async {
    final fakeApi = FakeApiService(
      parseMealResult: const MealParseResult(
        items: [],
        totalKcal: 300,
        mealType: 'dinner',
        modelLatencyMs: 300,
      ),
    );
    final container = ProviderContainer(
      overrides: [apiServiceProvider.overrideWithValue(fakeApi)],
    );
    addTearDown(container.dispose);

    await container.read(mealSessionProvider(date).future);
    final notifier = container.read(mealSessionProvider(date).notifier);
    await notifier.submitMeal('steak');
    final logged = container.read(mealSessionProvider(date)).value!.single;

    // Cache historyProvider's state with the entry present.
    final withEntry = await container.read(historyProvider.future);
    final withEntryDay = withEntry.days.singleWhere((d) => d.date == date);
    expect(withEntryDay.totalKcal, 300);

    await notifier.deleteEntry(logged.id);

    final afterDelete = await container.read(historyProvider.future);
    final afterDeleteToday = afterDelete.days.where((d) => d.date == date);
    final afterDeleteTotal = afterDeleteToday.isEmpty ? 0.0 : afterDeleteToday.single.totalKcal;
    expect(
      afterDeleteTotal,
      0.0,
      reason: 'historyProvider must be invalidated after deleteEntry so the '
          'cached AsyncNotifier state is not stale',
    );
  });
}
