import 'package:flutter/material.dart';
import '../core/app_theme.dart';
import '../widgets/day_ring.dart';
import '../widgets/meal_input_bar.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  static const _meals = [
    _MealEntry('2 eggs and toast', 320),
    _MealEntry('Chicken salad', 450),
    _MealEntry('Greek yoghurt', 180),
  ];

  static const _rings = [
    _RingData('Mon', 1800, 0.90, false),
    _RingData('Tue', 2200, 1.10, false),
    _RingData('Wed', 950,  0.48, false),
    _RingData('Thu', 1950, 0.98, true),
    _RingData('Fri', 0,    0.0,  false),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text('calAI', style: AppText.labelLg.copyWith(fontSize: 20)),
      ),
      body: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.screenEdge, AppSpacing.inner,
              AppSpacing.screenEdge, 0,
            ),
            child: const MealInputBar(onSubmit: null),
          ),
          const SizedBox(height: AppSpacing.sectionGap),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenEdge),
            child: Align(
              alignment: Alignment.centerLeft,
              child: Text("TODAY'S MEALS", style: AppText.labelSm),
            ),
          ),
          const SizedBox(height: AppSpacing.micro),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(
                horizontal: AppSpacing.screenEdge,
                vertical: AppSpacing.micro,
              ),
              itemCount: _meals.length,
              separatorBuilder: (context, i) => const SizedBox(height: 8),
              itemBuilder: (context, index) {
                final meal = _meals[index];
                return Dismissible(
                  key: ValueKey(meal.name),
                  direction: DismissDirection.endToStart,
                  background: Container(
                    alignment: Alignment.centerRight,
                    padding: const EdgeInsets.only(right: AppSpacing.inner),
                    decoration: BoxDecoration(
                      color: AppColors.signalRed.withValues(alpha: 0.15),
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: const Icon(
                      Icons.delete_outline,
                      color: AppColors.signalRed,
                    ),
                  ),
                  onDismissed: (_) {},
                  child: Container(
                    decoration: BoxDecoration(
                      color: AppColors.bgCard,
                      borderRadius: BorderRadius.circular(12),
                      boxShadow: const [
                        BoxShadow(
                          color: Colors.black38,
                          blurRadius: 8,
                          offset: Offset(0, 2),
                        ),
                      ],
                    ),
                    child: ListTile(
                      title: Text(meal.name, style: AppText.body.copyWith(
                        color: AppColors.inkPrimary,
                      )),
                      trailing: Text(
                        '${meal.kcal}',
                        style: AppText.numSection.copyWith(
                          color: AppColors.signalGreen,
                          fontSize: 16,
                        ),
                      ),
                    ),
                  ),
                );
              },
            ),
          ),
          const SizedBox(height: AppSpacing.micro),
          Container(
            padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.screenEdge,
              vertical: AppSpacing.inner,
            ),
            decoration: BoxDecoration(
              color: AppColors.bgCard,
              boxShadow: [
                BoxShadow(
                  color: Colors.black.withValues(alpha: 0.3),
                  blurRadius: 12,
                  offset: const Offset(0, -2),
                ),
              ],
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceEvenly,
              children: _rings
                  .map((r) => Expanded(
                        child: DayRing(
                          dayLabel: r.day,
                          kcal: r.kcal,
                          progress: r.progress,
                          isToday: r.isToday,
                        ),
                      ))
                  .toList(),
            ),
          ),
        ],
      ),
    );
  }
}

class _MealEntry {
  final String name;
  final int kcal;
  const _MealEntry(this.name, this.kcal);
}

class _RingData {
  final String day;
  final int kcal;
  final double progress;
  final bool isToday;
  const _RingData(this.day, this.kcal, this.progress, this.isToday);
}
