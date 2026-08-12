import 'dart:math';
import 'package:flutter/material.dart';
import '../core/app_theme.dart';

class DayRing extends StatelessWidget {
  final String dayLabel;
  final int kcal;
  final double progress;
  final bool isToday;

  const DayRing({
    super.key,
    required this.dayLabel,
    required this.kcal,
    required this.progress,
    this.isToday = false,
  });

  static Color _ringColor(double progress) {
    if (progress < 0.80) return AppColors.signalGrey;
    if (progress <= 1.00) {
      return Color.lerp(AppColors.signalGrey, AppColors.signalGreen,
          (progress - 0.80) / 0.20)!;
    }
    if (progress <= 1.15) {
      return Color.lerp(AppColors.signalGreen, AppColors.signalAmber,
          (progress - 1.00) / 0.15)!;
    }
    return Color.lerp(AppColors.signalAmber, AppColors.signalRed,
        ((progress - 1.15) / 0.10).clamp(0.0, 1.0))!;
  }

  @override
  Widget build(BuildContext context) {
    final zoneColor = _ringColor(progress);

    return Container(
      decoration: isToday
          ? BoxDecoration(
              borderRadius: BorderRadius.circular(12),
              boxShadow: [
                BoxShadow(
                  color: zoneColor.withValues(alpha: 0.30),
                  blurRadius: 20,
                  spreadRadius: 0,
                ),
              ],
            )
          : null,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          SizedBox(
            width: 56,
            height: 56,
            child: CustomPaint(
              painter: _RingPainter(
                progress: progress.clamp(0.0, 1.15),
                color: zoneColor,
              ),
              child: Center(
                child: Text(
                  '$kcal',
                  style: AppText.numSmall.copyWith(fontSize: 11),
                ),
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.micro),
          Text(
            dayLabel.toUpperCase(),
            style: AppText.labelSm.copyWith(
              fontSize: 10,
              fontWeight: isToday ? FontWeight.w700 : FontWeight.w500,
              color: isToday ? AppColors.accentIce : AppColors.inkSecondary,
            ),
          ),
        ],
      ),
    );
  }
}

class _RingPainter extends CustomPainter {
  final double progress;
  final Color color;

  const _RingPainter({required this.progress, required this.color});

  static const double _startAngle = 135 * pi / 180;
  static const double _sweepTotal = 270 * pi / 180;
  static const double _strokeWidth = 7.0;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = (size.width - _strokeWidth) / 2;
    final rect = Rect.fromCircle(center: center, radius: radius);

    final trackPaint = Paint()
      ..color = AppColors.signalGrey
      ..style = PaintingStyle.stroke
      ..strokeWidth = _strokeWidth
      ..strokeCap = StrokeCap.round;

    final fillPaint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = _strokeWidth
      ..strokeCap = StrokeCap.round;

    canvas.drawArc(rect, _startAngle, _sweepTotal, false, trackPaint);

    if (progress > 0) {
      canvas.drawArc(
        rect,
        _startAngle,
        _sweepTotal * progress,
        false,
        fillPaint,
      );
    }
  }

  @override
  bool shouldRepaint(_RingPainter old) =>
      old.progress != progress || old.color != color;
}
