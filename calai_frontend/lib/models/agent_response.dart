import 'calc_response.dart';
import 'user_profile.dart';

/// Mirrors `AgentMessageType` (calai_backend/schemas.py) exactly.
enum AgentMessageType {
  info,
  slotFillQuestion,
  profileConfirmation,
  recommendation,
  weeklyCheckin;

  String get value => switch (this) {
        AgentMessageType.info => 'info',
        AgentMessageType.slotFillQuestion => 'slot_fill_question',
        AgentMessageType.profileConfirmation => 'profile_confirmation',
        AgentMessageType.recommendation => 'recommendation',
        AgentMessageType.weeklyCheckin => 'weekly_checkin',
      };

  static AgentMessageType fromValue(String value) =>
      AgentMessageType.values.firstWhere((e) => e.value == value, orElse: () => AgentMessageType.info);
}

class SlotFillPayload {
  final List<String> missing;
  const SlotFillPayload({required this.missing});

  factory SlotFillPayload.fromJson(Map<String, dynamic> json) => SlotFillPayload(
        missing: (json['missing'] as List<dynamic>).map((e) => e as String).toList(),
      );
}

class ProfileConfirmationPayload {
  final UserProfile profile;
  final CalcResponse preview;
  const ProfileConfirmationPayload({required this.profile, required this.preview});

  factory ProfileConfirmationPayload.fromJson(Map<String, dynamic> json) => ProfileConfirmationPayload(
        profile: UserProfile.fromJson(json['profile'] as Map<String, dynamic>),
        preview: CalcResponse.fromJson(json['preview'] as Map<String, dynamic>),
      );
}

class RecommendationPayload {
  final double calorieGoalKcal;
  final double tdeeKcal;
  final double bmrKcal;
  final String rationale;

  const RecommendationPayload({
    required this.calorieGoalKcal,
    required this.tdeeKcal,
    required this.bmrKcal,
    required this.rationale,
  });

  factory RecommendationPayload.fromJson(Map<String, dynamic> json) => RecommendationPayload(
        calorieGoalKcal: (json['calorie_goal_kcal'] as num).toDouble(),
        tdeeKcal: (json['tdee_kcal'] as num).toDouble(),
        bmrKcal: (json['bmr_kcal'] as num).toDouble(),
        rationale: json['rationale'] as String,
      );
}

class WeeklyCheckinPayload {
  final double? lastWeightKg;
  const WeeklyCheckinPayload({this.lastWeightKg});

  factory WeeklyCheckinPayload.fromJson(Map<String, dynamic> json) => WeeklyCheckinPayload(
        lastWeightKg: (json['last_weight_kg'] as num?)?.toDouble(),
      );
}

/// Mirrors `AgentResponse` (calai_backend/schemas.py). Exactly one of the
/// four payload fields is non-null when `messageType != AgentMessageType.info`;
/// all four are null on `info`.
class AgentResponse {
  final String response;
  final int iterationsUsed;
  final AgentMessageType messageType;
  final SlotFillPayload? slotFill;
  final ProfileConfirmationPayload? profileConfirmation;
  final RecommendationPayload? recommendation;
  final WeeklyCheckinPayload? weeklyCheckin;

  const AgentResponse({
    required this.response,
    required this.iterationsUsed,
    this.messageType = AgentMessageType.info,
    this.slotFill,
    this.profileConfirmation,
    this.recommendation,
    this.weeklyCheckin,
  });

  factory AgentResponse.fromJson(Map<String, dynamic> json) {
    return AgentResponse(
      response: json['response'] as String,
      iterationsUsed: json['iterations_used'] as int,
      messageType: AgentMessageType.fromValue(json['message_type'] as String? ?? 'info'),
      slotFill: json['slot_fill'] == null
          ? null
          : SlotFillPayload.fromJson(json['slot_fill'] as Map<String, dynamic>),
      profileConfirmation: json['profile_confirmation'] == null
          ? null
          : ProfileConfirmationPayload.fromJson(json['profile_confirmation'] as Map<String, dynamic>),
      recommendation: json['recommendation'] == null
          ? null
          : RecommendationPayload.fromJson(json['recommendation'] as Map<String, dynamic>),
      weeklyCheckin: json['weekly_checkin'] == null
          ? null
          : WeeklyCheckinPayload.fromJson(json['weekly_checkin'] as Map<String, dynamic>),
    );
  }
}
