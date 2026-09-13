import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_service.dart';
import '../models/meal_entry.dart';
import 'user_provider.dart' show apiServiceProvider, storageServiceProvider;

DateTime dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);

String inferMealType(DateTime at) {
  final hour = at.hour;
  if (hour >= 5 && hour < 11) return 'breakfast';
  if (hour >= 11 && hour < 16) return 'lunch';
  if (hour >= 16 && hour < 21) return 'dinner';
  return 'snack';
}

/// One entry feed per calendar day (SKILL.md's per-date session model).
/// `dateOnly` keys keep "today" and a past day (opened via the history
/// sheet) as distinct provider instances.
final mealSessionProvider =
    AsyncNotifierProvider.family<MealSessionNotifier, List<MealEntry>, DateTime>(
  MealSessionNotifier.new,
);

class MealSessionNotifier extends AsyncNotifier<List<MealEntry>> {
  MealSessionNotifier(DateTime date) : date = dateOnly(date);

  final DateTime date;

  @override
  Future<List<MealEntry>> build() {
    return ref.read(storageServiceProvider).loadEntriesForDate(date);
  }

  List<MealEntry> get _current => state.value ?? const [];

  void _replace(MealEntry updated) {
    state = AsyncValue.data([
      for (final e in _current) if (e.id == updated.id) updated else e,
    ]);
  }

  Future<void> submitMeal(String text) async {
    final pending = MealEntry.pending(text, mealType: inferMealType(DateTime.now()));
    state = AsyncValue.data([..._current, pending]);
    await _resolve(pending);
  }

  Future<void> retry(String entryId) async {
    final entry = _current.firstWhere((e) => e.id == entryId);
    _replace(
      MealEntry(
        id: entry.id,
        rawText: entry.rawText,
        mealType: entry.mealType,
        status: EntryStatus.pending,
        timestamp: entry.timestamp,
      ),
    );
    await _resolve(_current.firstWhere((e) => e.id == entryId));
  }

  Future<void> _resolve(MealEntry pending) async {
    try {
      final MealParseResult result =
          await ref.read(apiServiceProvider).parseMeal(pending.rawText, mealType: pending.mealType);
      final logged = pending.asLogged(
        items: result.items,
        totalKcal: result.totalKcal,
        mealType: result.mealType,
      );
      await ref.read(storageServiceProvider).appendEntry(logged, date);
      _replace(logged);
    } catch (e) {
      _replace(pending.asError("Couldn't log — tap to retry"));
    }
  }

  Future<void> deleteEntry(String entryId) async {
    await ref.read(storageServiceProvider).deleteEntry(entryId, date);
    state = AsyncValue.data(_current.where((e) => e.id != entryId).toList());
  }
}
