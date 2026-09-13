/// ADR-007 Part 3 — minimal weight-history sample.
class WeightSample {
  final double weightKg;
  final DateTime at;

  const WeightSample({required this.weightKg, required this.at});

  Map<String, dynamic> toJson() => {
        'weightKg': weightKg,
        'at': at.toIso8601String(),
      };

  factory WeightSample.fromJson(Map<String, dynamic> json) {
    return WeightSample(
      weightKg: (json['weightKg'] as num).toDouble(),
      at: DateTime.parse(json['at'] as String),
    );
  }
}
