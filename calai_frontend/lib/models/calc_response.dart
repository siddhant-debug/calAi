/// Mirrors `CalcResponse` (calai_backend/schemas.py).
class CalcResponse {
  final double bmrKcal;
  final double tdeeKcal;
  final double calorieGoalKcal;

  const CalcResponse({
    required this.bmrKcal,
    required this.tdeeKcal,
    required this.calorieGoalKcal,
  });

  factory CalcResponse.fromJson(Map<String, dynamic> json) {
    return CalcResponse(
      bmrKcal: (json['bmr_kcal'] as num).toDouble(),
      tdeeKcal: (json['tdee_kcal'] as num).toDouble(),
      calorieGoalKcal: (json['calorie_goal_kcal'] as num).toDouble(),
    );
  }
}
