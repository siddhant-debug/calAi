import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/app_theme.dart';
import '../models/conversation_message.dart';
import '../models/user_profile.dart';
import '../providers/user_provider.dart';
import '../widgets/agent_message.dart';
import '../widgets/meal_input_bar.dart';

/// A single scrolling conversational thread — onboarding is the first
/// exchange in "a fresh chat thread," not a wizard (SKILL.md "Onboarding
/// screen").
class OnboardingScreen extends ConsumerStatefulWidget {
  const OnboardingScreen({super.key});

  @override
  ConsumerState<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends ConsumerState<OnboardingScreen> {
  final _scrollController = ScrollController();

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

  Future<void> _onConfirm(UserProfile profile) async {
    await ref.read(userProvider.notifier).confirm(profile);
    final state = ref.read(userProvider);
    if (state.hasValue && state.value != null && mounted) {
      context.go('/home');
    }
  }

  @override
  Widget build(BuildContext context) {
    final messagesAsync = ref.watch(onboardingProvider);
    final messages = messagesAsync.value ?? const <ConversationMessage>[];

    ref.listen(onboardingProvider, (previous, next) {
      final prevLen = previous?.value?.length ?? 0;
      final nextLen = next.value?.length ?? 0;
      if (nextLen > prevLen) _scrollToBottom();
    });

    return Scaffold(
      backgroundColor: AppColors.bgDeep,
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: messages.isEmpty
                  ? _EmptyState()
                  : ListView.separated(
                      controller: _scrollController,
                      padding: const EdgeInsets.symmetric(
                        horizontal: AppSpacing.screenEdge,
                        vertical: AppSpacing.inner,
                      ),
                      itemCount: messages.length,
                      separatorBuilder: (context, i) => const SizedBox(height: 8),
                      itemBuilder: (context, i) {
                        final message = messages[i];
                        if (message.role == ConversationRole.user) {
                          return Align(
                            alignment: Alignment.centerLeft,
                            child: Text(message.text, style: AppText.labelLg),
                          );
                        }
                        return AgentMessage(
                          response: message.agentResponse!,
                          onConfirm: (profile) => _onConfirm(profile),
                        );
                      },
                    ),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.screenEdge, AppSpacing.inner, AppSpacing.screenEdge, AppSpacing.inner,
              ),
              child: MealInputBar(
                hintText: 'Tell me about yourself…',
                onSubmit: (text) => ref.read(onboardingProvider.notifier).sendMessage(text),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.screenEdge),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Tell me about yourself and your goal.', style: AppText.labelLg),
            const SizedBox(height: AppSpacing.micro),
            Text(
              '"I\'m 60kg, want to gain 8kg over 4 months, get stronger, eat clean, not force-fed."',
              style: AppText.body,
            ),
          ],
        ),
      ),
    );
  }
}
