import 'package:flutter/material.dart';
import '../core/app_theme.dart';

/// The diary's signature element — a single colour-coded hero number, one
/// thin accent line, one compact macro row. Not a dashboard (SKILL.md
/// "Status strip"). Always visible, including the zero-entries state.
class StatusStrip extends StatelessWidget {
  final double totalKcal;
  final double goalKcal;
  final double proteinG;
  final double carbsG;
  final double fatG;

  const StatusStrip({
    super.key,
    required this.totalKcal,
    required this.goalKcal,
    required this.proteinG,
    required this.carbsG,
    required this.fatG,
  });

  double get _progress => goalKcal > 0 ? totalKcal / goalKcal : 0;

  @override
  Widget build(BuildContext context) {
    final progress = _progress;
    final targetColor = AppColors.zoneColor(progress);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TweenAnimationBuilder<Color?>(
          tween: ColorTween(begin: targetColor, end: targetColor),
          duration: const Duration(milliseconds: 300),
          curve: Curves.easeInOut,
          builder: (context, color, child) => Text(
            totalKcal.toStringAsFixed(0),
            style: AppText.numDisplay.copyWith(color: color),
          ),
        ),
        Text('of ${goalKcal.toStringAsFixed(0)} kcal', style: AppText.numSmall),
        const SizedBox(height: AppSpacing.micro),
        LayoutBuilder(
          builder: (context, constraints) {
            final fillWidth = constraints.maxWidth * progress.clamp(0.0, 1.0);
            return Stack(
              children: [
                Container(
                  height: 2,
                  decoration: BoxDecoration(
                    color: AppColors.bgSurface,
                    borderRadius: BorderRadius.circular(1),
                  ),
                ),
                AnimatedContainer(
                  duration: const Duration(milliseconds: 300),
                  curve: Curves.easeInOut,
                  height: 2,
                  width: fillWidth,
                  decoration: BoxDecoration(
                    color: targetColor,
                    borderRadius: BorderRadius.circular(1),
                  ),
                ),
              ],
            );
          },
        ),
        const SizedBox(height: AppSpacing.inner - AppSpacing.micro),
        Row(
          children: [
            _macro('P', proteinG),
            _dot(),
            _macro('C', carbsG),
            _dot(),
            _macro('F', fatG),
          ],
        ),
      ],
    );
  }

  Widget _macro(String label, double grams) => Text.rich(
        TextSpan(
          children: [
            TextSpan(text: '$label ', style: AppText.labelSm),
            TextSpan(text: '${grams.toStringAsFixed(0)}g', style: AppText.numSmall),
          ],
        ),
      );

  Widget _dot() => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 6),
        child: Text('·', style: AppText.labelSm.copyWith(color: AppColors.inkMuted)),
      );
}
