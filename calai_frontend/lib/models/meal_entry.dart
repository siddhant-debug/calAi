enum ItemConfidence {
  high,
  medium,
  low;

  String get value => name;

  static ItemConfidence fromValue(String value) =>
      ItemConfidence.values.firstWhere((e) => e.value == value, orElse: () => ItemConfidence.medium);
}

/// Mirrors `MealItem` (calai_backend/schemas.py).
class MealItem {
  final String name;
  final double quantity;
  final String unit;
  final double caloriesKcal;
  final double proteinG;
  final double carbsG;
  final double fatG;
  final ItemConfidence confidence;

  const MealItem({
    required this.name,
    required this.quantity,
    required this.unit,
    required this.caloriesKcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
    this.confidence = ItemConfidence.medium,
  });

  factory MealItem.fromJson(Map<String, dynamic> json) {
    return MealItem(
      name: json['name'] as String,
      quantity: (json['quantity'] as num).toDouble(),
      unit: json['unit'] as String,
      caloriesKcal: (json['calories_kcal'] as num).toDouble(),
      proteinG: (json['protein_g'] as num).toDouble(),
      carbsG: (json['carbs_g'] as num).toDouble(),
      fatG: (json['fat_g'] as num).toDouble(),
      confidence: ItemConfidence.fromValue(json['confidence'] as String? ?? 'medium'),
    );
  }

  Map<String, dynamic> toJson() => {
        'name': name,
        'quantity': quantity,
        'unit': unit,
        'calories_kcal': caloriesKcal,
        'protein_g': proteinG,
        'carbs_g': carbsG,
        'fat_g': fatG,
        'confidence': confidence.value,
      };
}

enum EntryStatus { pending, logged, error }

/// One card in the diary's entry feed. A submission starts `pending` (the
/// user's raw text only, no numbers yet — the request is 9-40s in flight),
/// transitions to `logged` once `/api/parse-meal` responds, or to `error` if
/// it fails. `id` is a client-generated identifier, stable across that
/// transition, so the feed can find-and-replace the same card in place.
class MealEntry {
  final String id;
  final String rawText;
  final String mealType;
  final EntryStatus status;
  final List<MealItem> items;
  final double totalKcal;
  final DateTime timestamp;
  final String? errorMessage;

  const MealEntry({
    required this.id,
    required this.rawText,
    required this.mealType,
    required this.status,
    required this.timestamp,
    this.items = const [],
    this.totalKcal = 0,
    this.errorMessage,
  });

  factory MealEntry.pending(String rawText, {required String mealType, DateTime? timestamp}) {
    return MealEntry(
      id: '${DateTime.now().microsecondsSinceEpoch}',
      rawText: rawText,
      mealType: mealType,
      status: EntryStatus.pending,
      timestamp: timestamp ?? DateTime.now(),
    );
  }

  MealEntry asLogged({
    required List<MealItem> items,
    required double totalKcal,
    required String mealType,
  }) {
    return MealEntry(
      id: id,
      rawText: rawText,
      mealType: mealType,
      status: EntryStatus.logged,
      timestamp: timestamp,
      items: items,
      totalKcal: totalKcal,
    );
  }

  MealEntry asError(String message) {
    return MealEntry(
      id: id,
      rawText: rawText,
      mealType: mealType,
      status: EntryStatus.error,
      timestamp: timestamp,
      errorMessage: message,
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'raw_text': rawText,
        'meal_type': mealType,
        'status': status.name,
        'items': items.map((e) => e.toJson()).toList(),
        'total_kcal': totalKcal,
        'timestamp': timestamp.toIso8601String(),
        'error_message': errorMessage,
      };

  factory MealEntry.fromJson(Map<String, dynamic> json) {
    return MealEntry(
      id: json['id'] as String,
      rawText: json['raw_text'] as String,
      mealType: json['meal_type'] as String,
      status: EntryStatus.values.firstWhere((e) => e.name == json['status'] as String),
      items: (json['items'] as List<dynamic>? ?? [])
          .map((e) => MealItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalKcal: (json['total_kcal'] as num?)?.toDouble() ?? 0,
      timestamp: DateTime.parse(json['timestamp'] as String),
      errorMessage: json['error_message'] as String?,
    );
  }
}
