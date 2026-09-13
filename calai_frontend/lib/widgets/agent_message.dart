import 'package:flutter/material.dart';

import '../core/app_theme.dart';
import '../models/agent_response.dart';
import '../models/user_profile.dart';

/// Renders one agent turn in the conversational thread (onboarding, and any
/// future chat surface the diary reuses this for). Switches on
/// `AgentResponse.messageType` and reads exactly the matching payload field
/// per ADR-007 Part 1 — no prose parsing.
///
/// `profileConfirmation` and `weeklyCheckin` layouts beyond plain text are
/// not literally spec'd in skills/flutter-dev/SKILL.md's "Onboarding screen"
/// section for the recommendation/check-in kinds specifically — composed
/// here from already-approved primitives only (bgCard, body, labelSm/
/// numSection pairing), no new tokens invented. Flag to ui-engineer if a
/// different layout is wanted.
class AgentMessage extends StatelessWidget {
  final AgentResponse response;
  final ValueChanged<UserProfile>? onConfirm;

  const AgentMessage({super.key, required this.response, this.onConfirm});

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder<double>(
      tween: Tween(begin: 0, end: 1),
      duration: const Duration(milliseconds: 200),
      builder: (context, opacity, child) => Opacity(opacity: opacity, child: child),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.inner),
        decoration: BoxDecoration(
          color: AppColors.bgCard,
          borderRadius: BorderRadius.circular(12),
        ),
        child: _buildBody(),
      ),
    );
  }

  Widget _buildBody() {
    switch (response.messageType) {
      case AgentMessageType.info:
      case AgentMessageType.slotFillQuestion:
        return Text(response.response, style: AppText.body);
      case AgentMessageType.profileConfirmation:
        final payload = response.profileConfirmation;
        if (payload == null) return Text(response.response, style: AppText.body);
        return _ConfirmationBody(payload: payload, onConfirm: onConfirm);
      case AgentMessageType.recommendation:
        final payload = response.recommendation;
        if (payload == null) return Text(response.response, style: AppText.body);
        return _RecommendationBody(payload: payload);
      case AgentMessageType.weeklyCheckin:
        final payload = response.weeklyCheckin;
        return _WeeklyCheckinBody(response: response.response, payload: payload);
    }
  }
}

class _ConfirmationBody extends StatelessWidget {
  final ProfileConfirmationPayload payload;
  final ValueChanged<UserProfile>? onConfirm;

  const _ConfirmationBody({required this.payload, this.onConfirm});

  @override
  Widget build(BuildContext context) {
    final profile = payload.profile;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text('PROFILE', style: AppText.labelSm),
        const SizedBox(height: AppSpacing.inner),
        _fieldRow('Weight', '${profile.weightKg?.toStringAsFixed(0)} kg'),
        _fieldRow(
          'Goal',
          '${profile.goal?.value ?? '—'} · ${profile.goalRateKgPerWeek} kg/wk',
        ),
        _fieldRow('Activity', profile.activityLevel?.value ?? '—'),
        _fieldRow('Height', '${profile.heightCm?.toStringAsFixed(0)} cm'),
        const Padding(
          padding: EdgeInsets.symmetric(vertical: AppSpacing.inner),
          child: Divider(height: 1),
        ),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('Daily target', style: AppText.labelSm),
            Text('${payload.preview.calorieGoalKcal.toStringAsFixed(0)} kcal', style: AppText.numSection),
          ],
        ),
        const SizedBox(height: AppSpacing.inner),
        _ConfirmButton(onTap: onConfirm == null ? null : () => onConfirm!(profile)),
        const SizedBox(height: AppSpacing.micro),
        Text(
          'Or just tell me what\'s wrong.',
          textAlign: TextAlign.center,
          style: AppText.body.copyWith(color: AppColors.inkMuted),
        ),
      ],
    );
  }

  Widget _fieldRow(String label, String value) => Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.micro),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(label, style: AppText.labelSm),
            Text(value, style: AppText.numSmall),
          ],
        ),
      );
}

class _ConfirmButton extends StatefulWidget {
  final VoidCallback? onTap;
  const _ConfirmButton({this.onTap});

  @override
  State<_ConfirmButton> createState() => _ConfirmButtonState();
}

class _ConfirmButtonState extends State<_ConfirmButton> {
  bool _pressed = false;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTapDown: (_) => setState(() => _pressed = true),
      onTapCancel: () => setState(() => _pressed = false),
      onTapUp: (_) => setState(() => _pressed = false),
      onTap: widget.onTap,
      child: AnimatedScale(
        scale: _pressed ? 0.95 : 1.0,
        duration: const Duration(milliseconds: 120),
        child: Container(
          width: double.infinity,
          height: 52,
          decoration: BoxDecoration(
            color: AppColors.accentIce,
            borderRadius: BorderRadius.circular(10),
          ),
          alignment: Alignment.center,
          child: Text('Confirm', style: AppText.labelLg.copyWith(color: AppColors.bgDeep)),
        ),
      ),
    );
  }
}

class _RecommendationBody extends StatelessWidget {
  final RecommendationPayload payload;
  const _RecommendationBody({required this.payload});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(payload.rationale, style: AppText.body),
        const SizedBox(height: AppSpacing.inner),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text('New daily target', style: AppText.labelSm),
            Text('${payload.calorieGoalKcal.toStringAsFixed(0)} kcal', style: AppText.numSection),
          ],
        ),
      ],
    );
  }
}

class _WeeklyCheckinBody extends StatelessWidget {
  final String response;
  final WeeklyCheckinPayload? payload;
  const _WeeklyCheckinBody({required this.response, this.payload});

  @override
  Widget build(BuildContext context) {
    final lastWeight = payload?.lastWeightKg;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(response, style: AppText.body),
        if (lastWeight != null) ...[
          const SizedBox(height: AppSpacing.micro),
          Text('Last recorded: ${lastWeight.toStringAsFixed(1)} kg', style: AppText.numSmall),
        ],
      ],
    );
  }
}
