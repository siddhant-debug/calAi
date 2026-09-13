import 'dart:convert';

import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/meal_entry.dart';
import '../models/user_profile.dart';
import '../models/weight_sample.dart';

/// ADR-007 Part 3 — client-side persistence, no server-side store.
/// Storage-only: wraps `SharedPreferences`, no other state or logic.
class StorageService {
  static const _profileKey = 'profile';
  static const _weightHistoryKey = 'weight_history';
  static const _lastCheckinAtKey = 'last_checkin_at';

  static final _dateFormat = DateFormat('yyyy-MM-dd');

  String _entriesKey(DateTime date) => 'entries_${_dateFormat.format(date)}';

  Future<UserProfile?> loadProfile() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_profileKey);
    if (raw == null) return null;
    return UserProfile.fromJson(jsonDecode(raw) as Map<String, dynamic>);
  }

  Future<void> saveProfile(UserProfile profile) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_profileKey, jsonEncode(profile.toJson()));
  }

  Future<void> clearProfile() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_profileKey);
  }

  Future<List<MealEntry>> loadEntriesForDate(DateTime date) async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_entriesKey(date));
    if (raw == null) return [];
    return (jsonDecode(raw) as List<dynamic>)
        .map((e) => MealEntry.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> appendEntry(MealEntry entry, DateTime date) async {
    final prefs = await SharedPreferences.getInstance();
    final entries = await loadEntriesForDate(date);
    entries.add(entry);
    await prefs.setString(
      _entriesKey(date),
      jsonEncode(entries.map((e) => e.toJson()).toList()),
    );
  }

  Future<void> deleteEntry(String entryId, DateTime date) async {
    final prefs = await SharedPreferences.getInstance();
    final entries = await loadEntriesForDate(date);
    entries.removeWhere((e) => e.id == entryId);
    await prefs.setString(
      _entriesKey(date),
      jsonEncode(entries.map((e) => e.toJson()).toList()),
    );
  }

  Future<List<WeightSample>> loadWeightHistory() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_weightHistoryKey);
    if (raw == null) return [];
    return (jsonDecode(raw) as List<dynamic>)
        .map((e) => WeightSample.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  Future<void> appendWeightSample(WeightSample sample) async {
    final prefs = await SharedPreferences.getInstance();
    final history = await loadWeightHistory();
    history.add(sample);
    await prefs.setString(
      _weightHistoryKey,
      jsonEncode(history.map((e) => e.toJson()).toList()),
    );
  }

  Future<DateTime?> loadLastCheckinAt() async {
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString(_lastCheckinAtKey);
    if (raw == null) return null;
    return DateTime.parse(raw);
  }

  Future<void> saveLastCheckinAt(DateTime at) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_lastCheckinAtKey, at.toIso8601String());
  }
}
