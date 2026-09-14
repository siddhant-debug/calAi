import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../widgets/history_sheet.dart';
import 'meal_provider.dart' show dateOnly;
import 'user_provider.dart' show storageServiceProvider;

/// Aggregated data for the history sheet: the latest recorded weight and a
/// flat 30-day scan of logged totals (SKILL.md "History sheet"). Kept as a
/// provider — not inlined in `home_screen.dart` — so the day-aggregation
/// logic is testable via `ProviderContainer` like the rest of the
/// persistence-touching logic (see `meal_provider_test.dart`).
class HistoryState {
  final double? latestWeightKg;
  final List<HistoryDay> days;
  const HistoryState({required this.latestWeightKg, required this.days});
}

final historyProvider = AsyncNotifierProvider<HistoryNotifier, HistoryState>(HistoryNotifier.new);

class HistoryNotifier extends AsyncNotifier<HistoryState> {
  @override
  Future<HistoryState> build() async {
    final storage = ref.read(storageServiceProvider);
    final weightHistory = await storage.loadWeightHistory();

    final days = <HistoryDay>[];
    for (var i = 0; i < 30; i++) {
      final date = dateOnly(DateTime.now()).subtract(Duration(days: i));
      final entries = await storage.loadEntriesForDate(date);
      if (entries.isEmpty) continue;
      final total = entries.fold<double>(0, (sum, e) => sum + e.totalKcal);
      days.add(HistoryDay(date: date, totalKcal: total));
    }

    return HistoryState(
      latestWeightKg: weightHistory.isEmpty ? null : weightHistory.last.weightKg,
      days: days,
    );
  }

  Future<void> refresh() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(build);
  }
}
