// One test per AgentMessageType (5 total), constructing an AgentResponse
// directly per ADR-007's schema — no live network call. Asserts each kind's
// distinguishing content actually renders.
//
// Note on slot_fill_question: agent_message.dart's current implementation
// (lib/widgets/agent_message.dart _buildBody) renders the same plain
// `response.response` text for both `info` and `slot_fill_question` — the
// `SlotFillPayload.missing` list itself is not rendered anywhere in the
// widget today. This test asserts the actual current behavior (prose text
// only), not the hypothetical "renders a missing-fields list" behavior;
// that gap is called out in this unit's report as a possible follow-up, not
// fixed here since tester doesn't own lib/.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:calai_frontend/models/agent_response.dart';
import 'package:calai_frontend/models/calc_response.dart';
import 'package:calai_frontend/models/user_profile.dart';
import 'package:calai_frontend/widgets/agent_message.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

void main() {
  testWidgets('info message renders the plain response text', (tester) async {
    await tester.pumpWidget(_wrap(const AgentMessage(
      response: AgentResponse(response: 'Hi, what can I help with?', iterationsUsed: 1),
    )));
    await tester.pumpAndSettle();

    expect(find.text('Hi, what can I help with?'), findsOneWidget);
  });

  testWidgets('slot_fill_question message renders its prose question', (tester) async {
    await tester.pumpWidget(_wrap(const AgentMessage(
      response: AgentResponse(
        response: "What's your age and goal?",
        iterationsUsed: 1,
        messageType: AgentMessageType.slotFillQuestion,
        slotFill: SlotFillPayload(missing: ['age', 'goal']),
      ),
    )));
    await tester.pumpAndSettle();

    expect(find.text("What's your age and goal?"), findsOneWidget);
  });

  testWidgets('profile_confirmation message renders the preview calorie goal and a Confirm button',
      (tester) async {
    const profile = UserProfile(
      weightKg: 70,
      heightCm: 175,
      age: 28,
      gender: Gender.male,
      activityLevel: ActivityLevel.moderatelyActive,
      goal: Goal.maintain,
    );
    const preview = CalcResponse(bmrKcal: 1600, tdeeKcal: 2200, calorieGoalKcal: 2000);

    await tester.pumpWidget(_wrap(const AgentMessage(
      response: AgentResponse(
        response: 'Here is your profile.',
        iterationsUsed: 2,
        messageType: AgentMessageType.profileConfirmation,
        profileConfirmation: ProfileConfirmationPayload(profile: profile, preview: preview),
      ),
    )));
    await tester.pumpAndSettle();

    expect(find.text('2000 kcal'), findsOneWidget);
    expect(find.text('Confirm'), findsOneWidget);
  });

  testWidgets('recommendation message renders the rationale and new daily target', (tester) async {
    await tester.pumpWidget(_wrap(const AgentMessage(
      response: AgentResponse(
        response: 'Adjusting your goal.',
        iterationsUsed: 1,
        messageType: AgentMessageType.recommendation,
        recommendation: RecommendationPayload(
          calorieGoalKcal: 2100,
          tdeeKcal: 2400,
          bmrKcal: 1700,
          rationale: 'Your last 3 weigh-ins are trending faster than your 0.5kg/week goal.',
        ),
      ),
    )));
    await tester.pumpAndSettle();

    expect(
      find.text('Your last 3 weigh-ins are trending faster than your 0.5kg/week goal.'),
      findsOneWidget,
    );
    expect(find.text('2100 kcal'), findsOneWidget);
  });

  testWidgets('weekly_checkin message renders the prompt and last recorded weight', (tester) async {
    await tester.pumpWidget(_wrap(const AgentMessage(
      response: AgentResponse(
        response: 'How much do you weigh this week?',
        iterationsUsed: 1,
        messageType: AgentMessageType.weeklyCheckin,
        weeklyCheckin: WeeklyCheckinPayload(lastWeightKg: 71.5),
      ),
    )));
    await tester.pumpAndSettle();

    expect(find.text('How much do you weigh this week?'), findsOneWidget);
    expect(find.text('Last recorded: 71.5 kg'), findsOneWidget);
  });

  testWidgets('weekly_checkin message with no prior weight omits the "Last recorded" line',
      (tester) async {
    await tester.pumpWidget(_wrap(const AgentMessage(
      response: AgentResponse(
        response: 'How much do you weigh this week?',
        iterationsUsed: 1,
        messageType: AgentMessageType.weeklyCheckin,
      ),
    )));
    await tester.pumpAndSettle();

    expect(find.text('How much do you weigh this week?'), findsOneWidget);
    expect(find.textContaining('Last recorded'), findsNothing);
  });
}
