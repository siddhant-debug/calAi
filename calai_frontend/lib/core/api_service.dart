import 'dart:convert';

import 'package:http/http.dart' as http;

import '../models/agent_response.dart';
import '../models/calc_response.dart';
import '../models/meal_entry.dart';
import '../models/user_profile.dart';

/// Thrown for any non-2xx response. `message` is `detail.message` from the
/// single normalized error envelope (`{"detail": {"message": str, "errors":
/// list|null}}`, per rules/backend-facts.md's P1 fix) — never a raw string-or-
/// list `detail`, that shape no longer exists.
class ApiException implements Exception {
  final int statusCode;
  final String message;
  final List<dynamic>? errors;

  const ApiException(this.statusCode, this.message, {this.errors});

  @override
  String toString() => 'ApiException($statusCode): $message';
}

/// HTTP-only: no app state lives here. Replace `<LOCAL_IP>` with your Mac's
/// LAN IP for real device / simulator use (see skills/flutter-dev/SKILL.md).
class ApiService {
  final String baseUrl;

  const ApiService({this.baseUrl = 'http://<LOCAL_IP>:8000/api'});

  Future<CalcResponse> calculate(UserProfile profile) async {
    final json = await _post('/calculate', profile.toJson());
    return CalcResponse.fromJson(json);
  }

  Future<MealParseResult> parseMeal(String mealText, {String mealType = 'snack'}) async {
    final json = await _post('/parse-meal', {
      'meal_text': mealText,
      'meal_type': mealType,
    });
    return MealParseResult.fromJson(json);
  }

  Future<AgentResponse> agent(
    String message, {
    UserProfile? profile,
    String trigger = 'message',
  }) async {
    final json = await _post('/agent', {
      'message': message,
      if (profile != null && profile.isComplete) 'profile': profile.toJson(),
      'trigger': trigger,
    });
    return AgentResponse.fromJson(json);
  }

  Future<Map<String, dynamic>> _post(String path, Map<String, dynamic> body) async {
    final http.Response response;
    try {
      response = await http.post(
        Uri.parse('$baseUrl$path'),
        headers: const {'Content-Type': 'application/json'},
        body: jsonEncode(body),
      );
    } catch (e) {
      throw ApiException(0, 'Could not reach the server: $e');
    }

    final decoded = response.body.isEmpty ? <String, dynamic>{} : jsonDecode(response.body);

    if (response.statusCode < 200 || response.statusCode >= 300) {
      final detail = decoded is Map<String, dynamic> ? decoded['detail'] : null;
      final message = detail is Map<String, dynamic>
          ? detail['message'] as String? ?? 'Request failed'
          : 'Request failed';
      final errors = detail is Map<String, dynamic> ? detail['errors'] as List<dynamic>? : null;
      throw ApiException(response.statusCode, message, errors: errors);
    }

    return decoded as Map<String, dynamic>;
  }
}

/// `/api/parse-meal`'s response — kept out of `MealEntry` since the entry
/// model also needs to represent pending/error states with no items yet.
class MealParseResult {
  final List<MealItem> items;
  final double totalKcal;
  final String mealType;
  final double modelLatencyMs;

  const MealParseResult({
    required this.items,
    required this.totalKcal,
    required this.mealType,
    required this.modelLatencyMs,
  });

  factory MealParseResult.fromJson(Map<String, dynamic> json) {
    return MealParseResult(
      items: (json['items'] as List<dynamic>)
          .map((e) => MealItem.fromJson(e as Map<String, dynamic>))
          .toList(),
      totalKcal: (json['total_kcal'] as num).toDouble(),
      mealType: json['meal_type'] as String,
      modelLatencyMs: (json['model_latency_ms'] as num).toDouble(),
    );
  }
}
