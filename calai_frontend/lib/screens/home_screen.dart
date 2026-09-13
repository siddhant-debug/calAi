import 'package:intl/intl.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/app_theme.dart';
import '../models/meal_entry.dart';
import '../providers/meal_provider.dart';
import '../providers/user_provider.dart';
import '../widgets/entry_card.dart';
import '../widgets/history_sheet.dart';
import '../widgets/meal_input_bar.dart';
import '../widgets/status_strip.dart';

/// Today's diary/session screen (SKILL.md "Today screen"). Opening a past
/// day via the history sheet swaps this same screen's data to that date —
/// not a new route.
class HomeScreen extends ConsumerStatefulWidget {
  const HomeScreen({super.key});

  @override
  ConsumerState<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends ConsumerState<HomeScreen> {
  DateTime _viewedDate = dateOnly(DateTime.now());
  final _scrollController = ScrollController();

  bool get _isToday => _viewedDate == dateOnly(DateTime.now());

  @override
  void dispose() {
    _scrollController.dispose();
    super.dispose();
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!_scrollController.hasClients) return;
      _scrollController.animateTo(
        _scrollController.position.maxScrollExtent,
        duration: const Duration(milliseconds: 200),
        curve: Curves.easeOut,
      );
    });
  }

  Future<void> _openHistory() async {
    final storage = ref.read(storageServiceProvider);
    final weightHistory = await storage.loadWeightHistory();
    final days = <HistoryDay>[];
    for (var i = 0; i < 30; i++) {
      final date = dateOnly(DateTime.now()).subtract(Duration(days: i));
      final entries = await storage.loadEntriesForDate(date);
      if (entries.isEmpty) continue;
      final total = entries.fold<double>(0, (sum, e) => sum + e.totalKcal);
      days.add(HistoryDay(date: date, totalKcal: total));
    }
    final goal = ref.read(calorieGoalProvider).value?.calorieGoalKcal ?? 0;

    if (!mounted) return;
    await showModalBottomSheet(
      context: context,
      backgroundColor: Colors.transparent,
      constraints: BoxConstraints(maxHeight: MediaQuery.of(context).size.height * 0.8),
      builder: (context) => HistorySheet(
        latestWeightKg: weightHistory.isEmpty ? null : weightHistory.last.weightKg,
        goalKcal: goal,
        days: days,
        onSelectDate: (date) {
          Navigator.of(context).pop();
          setState(() => _viewedDate = date);
        },
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final entriesAsync = ref.watch(mealSessionProvider(_viewedDate));
    final goalAsync = ref.watch(calorieGoalProvider);

    ref.listen(mealSessionProvider(_viewedDate), (previous, next) {
      final prevLen = previous?.value?.length ?? 0;
      final nextLen = next.value?.length ?? 0;
      if (nextLen > prevLen) _scrollToBottom();
    });

    final entries = entriesAsync.value ?? const <MealEntry>[];
    final goalKcal = goalAsync.value?.calorieGoalKcal ?? 0;
    final totalKcal = entries
        .where((e) => e.status == EntryStatus.logged)
        .fold<double>(0, (sum, e) => sum + e.totalKcal);
    final proteinG = entries
        .where((e) => e.status == EntryStatus.logged)
        .expand((e) => e.items)
        .fold<double>(0, (sum, i) => sum + i.proteinG);
    final carbsG = entries
        .where((e) => e.status == EntryStatus.logged)
        .expand((e) => e.items)
        .fold<double>(0, (sum, i) => sum + i.carbsG);
    final fatG = entries
        .where((e) => e.status == EntryStatus.logged)
        .expand((e) => e.items)
        .fold<double>(0, (sum, i) => sum + i.fatG);

    return Scaffold(
      backgroundColor: AppColors.bgDeep,
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenEdge, AppSpacing.inner, AppSpacing.screenEdge, 0,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  GestureDetector(
                    onTap: _openHistory,
                    child: Row(
                      children: [
                        Text(_headerLabel(), style: AppText.labelSm),
                        const SizedBox(width: 4),
                        const Icon(Icons.expand_more, size: 16, color: AppColors.inkSecondary),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.inner),
                  StatusStrip(
                    totalKcal: totalKcal,
                    goalKcal: goalKcal,
                    proteinG: proteinG,
                    carbsG: carbsG,
                    fatG: fatG,
                  ),
                ],
              ),
            ),
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.sectionGap),
              child: Divider(height: 1),
            ),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenEdge),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('ENTRIES', style: AppText.labelSm),
              ),
            ),
            const SizedBox(height: AppSpacing.inner),
            Expanded(
              child: entries.isEmpty
                  ? Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text('Nothing logged yet.', style: AppText.numSection),
                          const SizedBox(height: AppSpacing.micro),
                          Text('Type what you ate below.', style: AppText.body),
                        ],
                      ),
                    )
                  : ListView.separated(
                      controller: _scrollController,
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.screenEdge,
                        vertical: AppSpacing.micro,
                      ),
                      itemCount: entries.length,
                      separatorBuilder: (context, i) => const SizedBox(height: AppSpacing.inner),
                      itemBuilder: (context, i) {
                        final entry = entries[i];
                        final notifier = ref.read(mealSessionProvider(_viewedDate).notifier);
                        return EntryCard(
                          entry: entry,
                          index: i,
                          onDelete: () => notifier.deleteEntry(entry.id),
                          onRetry: entry.status == EntryStatus.error
                              ? () => notifier.retry(entry.id)
                              : null,
                        );
                      },
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenEdge, AppSpacing.inner, AppSpacing.screenEdge, AppSpacing.inner,
              ),
              child: MealInputBar(
                onSubmit: (text) =>
                    ref.read(mealSessionProvider(_viewedDate).notifier).submitMeal(text),
              ),
            ),
          ],
        ),
      ),
    );
  }

  String _headerLabel() {
    if (_isToday) {
      return 'TODAY · ${DateFormat('MMM d').format(_viewedDate).toUpperCase()}';
    }
    return DateFormat('MMM d · EEE').format(_viewedDate).toUpperCase();
  }
}
