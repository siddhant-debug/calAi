import 'package:calai_frontend/core/api_service.dart';
import 'package:calai_frontend/models/agent_response.dart';
import 'package:calai_frontend/models/calc_response.dart';
import 'package:calai_frontend/models/user_profile.dart';

/// Test double for [ApiService]. Overrides the three network methods so
/// provider/widget tests never hit a real socket — configure exactly the
/// response (or exception) a given test needs, everything else defaults to
/// a harmless stub that fails loudly (`StateError`) if it's ever called
/// unexpectedly.
class FakeApiService extends ApiService {
  FakeApiService({
    this.calcResponse,
    this.calcException,
    this.parseMealResult,
    this.parseMealException,
    this.agentResponse,
    this.agentException,
  });

  // Mutable (not final) so a test can flip a fake's behavior between calls
  // — e.g. simulating a retry that succeeds after an initial failure.
  CalcResponse? calcResponse;
  Object? calcException;
  MealParseResult? parseMealResult;
  Object? parseMealException;
  AgentResponse? agentResponse;
  Object? agentException;

  int calculateCallCount = 0;
  int parseMealCallCount = 0;
  int agentCallCount = 0;

  @override
  Future<CalcResponse> calculate(UserProfile profile) async {
    calculateCallCount++;
    if (calcException != null) throw calcException!;
    if (calcResponse != null) return calcResponse!;
    return const CalcResponse(bmrKcal: 1500, tdeeKcal: 2000, calorieGoalKcal: 1800);
  }

  @override
  Future<MealParseResult> parseMeal(String mealText, {String mealType = 'snack'}) async {
    parseMealCallCount++;
    if (parseMealException != null) throw parseMealException!;
    if (parseMealResult != null) return parseMealResult!;
    throw StateError('FakeApiService.parseMeal called with no result/exception configured');
  }

  @override
  Future<AgentResponse> agent(String message, {UserProfile? profile, String trigger = 'message'}) async {
    agentCallCount++;
    if (agentException != null) throw agentException!;
    if (agentResponse != null) return agentResponse!;
    throw StateError('FakeApiService.agent called with no response/exception configured');
  }
}
