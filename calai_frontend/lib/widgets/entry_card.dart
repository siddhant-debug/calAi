import 'package:intl/intl.dart';
import 'package:flutter/material.dart';

import '../core/app_theme.dart';
import '../models/meal_entry.dart';

/// One card per submission — raw text + total, with parsed items as chips
/// below (SKILL.md "Entry feed & Entry card"). Handles all three
/// pending/logged/error states.
class EntryCard extends StatelessWidget {
  final MealEntry entry;
  final VoidCallback onDelete;
  final VoidCallback? onRetry;
  final int index;

  const EntryCard({
    super.key,
    required this.entry,
    required this.onDelete,
    this.onRetry,
    this.index = 0,
  });

  @override
  Widget build(BuildContext context) {
    return _AppearAnimation(
      delay: Duration(milliseconds: index * 40),
      child: Dismissible(
        key: ValueKey(entry.id),
        direction: DismissDirection.endToStart,
        onDismissed: (_) => onDelete(),
        background: Container(
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: AppSpacing.inner),
          decoration: BoxDecoration(
            color: AppColors.signalRed,
            borderRadius: BorderRadius.circular(12),
          ),
          child: const Icon(Icons.delete_outline, color: AppColors.inkPrimary),
        ),
        child: GestureDetector(
          onTap: entry.status == EntryStatus.error ? onRetry : null,
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(AppSpacing.inner),
            decoration: BoxDecoration(
              color: AppColors.bgCard,
              borderRadius: BorderRadius.circular(12),
              border: entry.status == EntryStatus.error
                  ? const Border(left: BorderSide(color: AppColors.signalRed, width: 2))
                  : null,
              boxShadow: const [
                BoxShadow(color: Colors.black38, blurRadius: 8, offset: Offset(0, 2)),
              ],
            ),
            child: switch (entry.status) {
              EntryStatus.pending => _PendingBody(entry: entry),
              EntryStatus.logged => _LoggedBody(entry: entry),
              EntryStatus.error => _ErrorBody(entry: entry),
            },
          ),
        ),
      ),
    );
  }
}

class _PendingBody extends StatefulWidget {
  final MealEntry entry;
  const _PendingBody({required this.entry});

  @override
  State<_PendingBody> createState() => _PendingBodyState();
}

class _PendingBodyState extends State<_PendingBody> with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(milliseconds: 1200))
      ..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(widget.entry.rawText, style: AppText.labelLg),
        const SizedBox(height: AppSpacing.inner),
        SizedBox(
          height: 2,
          child: AnimatedBuilder(
            animation: _controller,
            builder: (context, _) {
              return LayoutBuilder(
                builder: (context, constraints) {
                  final segmentWidth = constraints.maxWidth * 0.4;
                  final travel = constraints.maxWidth + segmentWidth;
                  final x = _controller.value * travel - segmentWidth;
                  return Stack(
                    children: [
                      Container(color: AppColors.inkMuted),
                      Positioned(
                        left: x,
                        width: segmentWidth,
                        height: 2,
                        child: Container(color: AppColors.accentIce),
                      ),
                    ],
                  );
                },
              );
            },
          ),
        ),
      ],
    );
  }
}

class _LoggedBody extends StatelessWidget {
  final MealEntry entry;
  const _LoggedBody({required this.entry});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(child: Text(entry.rawText, style: AppText.labelLg)),
            Text(entry.totalKcal.toStringAsFixed(0), style: AppText.numSection),
          ],
        ),
        const SizedBox(height: AppSpacing.micro),
        Row(
          children: [
            Text(DateFormat('h:mm a').format(entry.timestamp), style: AppText.numSmall),
            Text(' · ${entry.mealType}', style: AppText.labelSm.copyWith(color: AppColors.inkMuted)),
          ],
        ),
        if (entry.items.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.inner),
          SizedBox(
            height: 28,
            child: ListView.separated(
              scrollDirection: Axis.horizontal,
              itemCount: entry.items.length,
              separatorBuilder: (context, i) => const SizedBox(width: 8),
              itemBuilder: (context, i) {
                final item = entry.items[i];
                return Container(
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  decoration: BoxDecoration(
                    color: AppColors.bgSurface,
                    borderRadius: BorderRadius.circular(6),
                  ),
                  alignment: Alignment.center,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      if (item.confidence == ItemConfidence.low) ...[
                        Container(
                          width: 6,
                          height: 6,
                          decoration: const BoxDecoration(
                            color: AppColors.signalAmber,
                            shape: BoxShape.circle,
                          ),
                        ),
                        const SizedBox(width: 6),
                      ],
                      Text(
                        '${item.name} · ${item.caloriesKcal.toStringAsFixed(0)}kcal',
                        style: AppText.numSmall,
                      ),
                    ],
                  ),
                );
              },
            ),
          ),
        ],
      ],
    );
  }
}

class _ErrorBody extends StatelessWidget {
  final MealEntry entry;
  const _ErrorBody({required this.entry});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(entry.rawText, style: AppText.labelLg),
        const SizedBox(height: AppSpacing.micro),
        Text(
          entry.errorMessage ?? "Couldn't log — tap to retry",
          style: AppText.labelSm.copyWith(color: AppColors.signalRed),
        ),
      ],
    );
  }
}

class _AppearAnimation extends StatefulWidget {
  final Widget child;
  final Duration delay;
  const _AppearAnimation({required this.child, required this.delay});

  @override
  State<_AppearAnimation> createState() => _AppearAnimationState();
}

class _AppearAnimationState extends State<_AppearAnimation> {
  bool _visible = false;

  @override
  void initState() {
    super.initState();
    Future.delayed(widget.delay, () {
      if (mounted) setState(() => _visible = true);
    });
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedSlide(
      offset: _visible ? Offset.zero : const Offset(0, 0.08),
      duration: const Duration(milliseconds: 200),
      child: AnimatedOpacity(
        opacity: _visible ? 1 : 0,
        duration: const Duration(milliseconds: 200),
        child: widget.child,
      ),
    );
  }
}
