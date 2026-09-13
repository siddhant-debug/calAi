// Round-trip coverage for StorageService (ADR-007 Part 3 persistence
// contract) — save then load each model and assert equality, backed by
// SharedPreferences.setMockInitialValues rather than a real device.

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:calai_frontend/core/storage_service.dart';
import 'package:calai_frontend/models/meal_entry.dart';
import 'package:calai_frontend/models/user_profile.dart';
import 'package:calai_frontend/models/weight_sample.dart';

void main() {
  late StorageService storage;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    storage = StorageService();
  });

  test('profile round-trips through save/load, and clearProfile removes it', () async {
    const profile = UserProfile(
      weightKg: 70,
      heightCm: 175,
      age: 28,
      gender: Gender.male,
      activityLevel: ActivityLevel.moderatelyActive,
      goal: Goal.maintain,
      goalRateKgPerWeek: 0.5,
    );

    expect(await storage.loadProfile(), isNull);

    await storage.saveProfile(profile);
    final loaded = await storage.loadProfile();

    expect(loaded, isNotNull);
    expect(loaded!.toJson(), profile.toJson());

    await storage.clearProfile();
    expect(await storage.loadProfile(), isNull);
  });

  test('meal entries round-trip per date, and deleteEntry removes only the target entry', () async {
    final date = DateTime(2026, 9, 14);
    final entry = MealEntry(
      id: 'e1',
      rawText: '2 eggs and toast',
      mealType: 'breakfast',
      status: EntryStatus.logged,
      items: const [
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
      timestamp: DateTime(2026, 9, 14, 8, 30),
    );
    final entry2 = MealEntry(
      id: 'e2',
      rawText: 'Chicken salad',
      mealType: 'lunch',
      status: EntryStatus.logged,
      timestamp: DateTime(2026, 9, 14, 12, 30),
      totalKcal: 400,
    );

    expect(await storage.loadEntriesForDate(date), isEmpty);

    await storage.appendEntry(entry, date);
    await storage.appendEntry(entry2, date);

    final loaded = await storage.loadEntriesForDate(date);
    expect(loaded, hasLength(2));
    expect(loaded.firstWhere((e) => e.id == 'e1').toJson(), entry.toJson());
    expect(loaded.firstWhere((e) => e.id == 'e2').toJson(), entry2.toJson());

    await storage.deleteEntry('e1', date);
    final afterDelete = await storage.loadEntriesForDate(date);
    expect(afterDelete, hasLength(1));
    expect(afterDelete.single.id, 'e2');
  });

  test('a different date has an independent, empty entry list', () async {
    final date = DateTime(2026, 9, 14);
    final otherDate = DateTime(2026, 9, 15);
    await storage.appendEntry(
      MealEntry(
        id: 'e1',
        rawText: 'toast',
        mealType: 'breakfast',
        status: EntryStatus.logged,
        timestamp: date,
      ),
      date,
    );

    expect(await storage.loadEntriesForDate(otherDate), isEmpty);
    expect(await storage.loadEntriesForDate(date), hasLength(1));
  });

  test('weight history round-trips via appendWeightSample', () async {
    final sample = WeightSample(weightKg: 71.5, at: DateTime(2026, 9, 14, 9, 0));

    expect(await storage.loadWeightHistory(), isEmpty);

    await storage.appendWeightSample(sample);
    final loaded = await storage.loadWeightHistory();

    expect(loaded, hasLength(1));
    expect(loaded.single.toJson(), sample.toJson());
  });

  test('last check-in timestamp round-trips through save/load', () async {
    expect(await storage.loadLastCheckinAt(), isNull);

    final at = DateTime(2026, 9, 14, 12, 0, 0);
    await storage.saveLastCheckinAt(at);

    expect(await storage.loadLastCheckinAt(), at);
  });
}
