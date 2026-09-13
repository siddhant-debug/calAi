enum Gender {
  male,
  female;

  String get value => name;

  static Gender fromValue(String value) =>
      Gender.values.firstWhere((e) => e.value == value);
}

enum ActivityLevel {
  sedentary,
  lightlyActive,
  moderatelyActive,
  veryActive,
  extraActive;

  String get value => switch (this) {
        ActivityLevel.sedentary => 'sedentary',
        ActivityLevel.lightlyActive => 'lightly_active',
        ActivityLevel.moderatelyActive => 'moderately_active',
        ActivityLevel.veryActive => 'very_active',
        ActivityLevel.extraActive => 'extra_active',
      };

  static ActivityLevel fromValue(String value) =>
      ActivityLevel.values.firstWhere((e) => e.value == value);
}

enum Goal {
  lose,
  maintain,
  gain;

  String get value => name;

  static Goal fromValue(String value) =>
      Goal.values.firstWhere((e) => e.value == value);
}

/// Mirrors `CalcRequest` (calai_backend/schemas.py). May be partially filled
/// during onboarding's conversational slot-filling — every field is nullable
/// except `goalRateKgPerWeek`, which carries the backend's own default so a
/// partial profile never needs a sentinel for it.
class UserProfile {
  final double? weightKg;
  final double? heightCm;
  final int? age;
  final Gender? gender;
  final ActivityLevel? activityLevel;
  final Goal? goal;
  final double goalRateKgPerWeek;

  const UserProfile({
    this.weightKg,
    this.heightCm,
    this.age,
    this.gender,
    this.activityLevel,
    this.goal,
    this.goalRateKgPerWeek = 0.5,
  });

  /// True once every field `CalcRequest` requires is present — the point at
  /// which onboarding can show the confirmation card / POST /api/calculate.
  bool get isComplete =>
      weightKg != null &&
      heightCm != null &&
      age != null &&
      gender != null &&
      activityLevel != null &&
      goal != null;

  UserProfile copyWith({
    double? weightKg,
    double? heightCm,
    int? age,
    Gender? gender,
    ActivityLevel? activityLevel,
    Goal? goal,
    double? goalRateKgPerWeek,
  }) {
    return UserProfile(
      weightKg: weightKg ?? this.weightKg,
      heightCm: heightCm ?? this.heightCm,
      age: age ?? this.age,
      gender: gender ?? this.gender,
      activityLevel: activityLevel ?? this.activityLevel,
      goal: goal ?? this.goal,
      goalRateKgPerWeek: goalRateKgPerWeek ?? this.goalRateKgPerWeek,
    );
  }

  /// Shaped exactly like `CalcRequest` — only valid to call once [isComplete].
  Map<String, dynamic> toJson() {
    assert(isComplete, 'toJson() called on an incomplete UserProfile');
    return {
      'weight_kg': weightKg,
      'height_cm': heightCm,
      'age': age,
      'gender': gender!.value,
      'activity_level': activityLevel!.value,
      'goal': goal!.value,
      'goal_rate_kg_per_week': goalRateKgPerWeek,
    };
  }

  factory UserProfile.fromJson(Map<String, dynamic> json) {
    return UserProfile(
      weightKg: (json['weight_kg'] as num?)?.toDouble(),
      heightCm: (json['height_cm'] as num?)?.toDouble(),
      age: json['age'] as int?,
      gender: json['gender'] == null ? null : Gender.fromValue(json['gender'] as String),
      activityLevel: json['activity_level'] == null
          ? null
          : ActivityLevel.fromValue(json['activity_level'] as String),
      goal: json['goal'] == null ? null : Goal.fromValue(json['goal'] as String),
      goalRateKgPerWeek: (json['goal_rate_kg_per_week'] as num?)?.toDouble() ?? 0.5,
    );
  }
}
