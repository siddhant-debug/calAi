import 'package:intl/intl.dart';
import 'package:flutter/material.dart';

import '../core/app_theme.dart';

/// One row of the flat chronological list — a day's total against that
/// day's goal (dot colour only, per SKILL.md "History sheet").
class HistoryDay {
  final DateTime date;
  final double totalKcal;
  const HistoryDay({required this.date, required this.totalKcal});
}

/// Bottom sheet for past-day navigation (SKILL.md "History sheet"). A dense
/// chronological list, not a calendar grid — each row opens that date on
/// the same diary screen (in-place session swap, not a new route).
///
/// The "vs expected weight · week N of M" goal-progress line described in
/// the spec needs a stored program-start date and total goal duration in
/// weeks — neither exists in ADR-007 Part 3's storage contract (only
/// `weight_history` samples and `last_checkin_at` are persisted). That line
/// is deliberately omitted here rather than invented; see this file's
/// entry in the flutter-engineer report for the open question.
class HistorySheet extends StatelessWidget {
  final double? latestWeightKg;
  final double goalKcal;
  final List<HistoryDay> days;
  final ValueChanged<DateTime> onSelectDate;

  const HistorySheet({
    super.key,
    required this.latestWeightKg,
    required this.goalKcal,
    required this.days,
    required this.onSelectDate,
  });

  @override
  Widget build(BuildContext context) {
    final sorted = [...days]..sort((a, b) => b.date.compareTo(a.date));

    return Container(
      decoration: const BoxDecoration(
        color: AppColors.bgCard,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Center(
              child: Container(
                margin: const EdgeInsets.only(top: 12),
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: AppColors.inkMuted,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenEdge, AppSpacing.inner, AppSpacing.screenEdge, 0,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('HISTORY', style: AppText.labelSm),
                  const SizedBox(height: AppSpacing.micro),
                  Text(
                    latestWeightKg != null ? '${latestWeightKg!.toStringAsFixed(1)} kg' : '—',
                    style: AppText.numSection,
                  ),
                ],
              ),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.inner),
              child: Divider(height: 1),
            ),
            Flexible(
              child: ListView.separated(
                shrinkWrap: true,
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenEdge),
                itemCount: sorted.length,
                separatorBuilder: (context, i) => const Divider(height: 1),
                itemBuilder: (context, i) {
                  final day = sorted[i];
                  final progress = goalKcal > 0 ? day.totalKcal / goalKcal : 0.0;
                  return InkWell(
                    onTap: () => onSelectDate(day.date),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: AppSpacing.inner),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text(DateFormat('MMM d   EEE').format(day.date), style: AppText.numSmall),
                          Row(
                            children: [
                              Text(day.totalKcal.toStringAsFixed(0), style: AppText.numSmall),
                              const SizedBox(width: 8),
                              Container(
                                width: 6,
                                height: 6,
                                decoration: BoxDecoration(
                                  color: AppColors.zoneColor(progress),
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}
