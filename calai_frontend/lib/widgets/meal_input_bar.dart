import 'package:flutter/material.dart';
import '../core/app_theme.dart';

/// The floating input bar used by both the diary (`home_screen.dart`) and
/// onboarding (`onboarding_screen.dart`) — same visual spec, placeholder
/// text swapped per screen. Always enabled: a second submission can be sent
/// while an earlier one is still in flight (SKILL.md's "Today screen").
class MealInputBar extends StatefulWidget {
  final ValueChanged<String>? onSubmit;
  final String hintText;

  const MealInputBar({
    super.key,
    this.onSubmit,
    this.hintText = 'What did you eat?',
  });

  @override
  State<MealInputBar> createState() => _MealInputBarState();
}

class _MealInputBarState extends State<MealInputBar> {
  final _focus = FocusNode();
  final _controller = TextEditingController();
  bool _isFocused = false;
  bool _pressed = false;

  @override
  void initState() {
    super.initState();
    _focus.addListener(() => setState(() => _isFocused = _focus.hasFocus));
  }

  @override
  void dispose() {
    _focus.dispose();
    _controller.dispose();
    super.dispose();
  }

  void _submit() {
    final text = _controller.text.trim();
    if (text.isEmpty || widget.onSubmit == null) return;
    widget.onSubmit!(text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      decoration: BoxDecoration(
        color: AppColors.bgSurface,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(
          color: _isFocused ? AppColors.accentIce : AppColors.inkMuted,
          width: _isFocused ? 1.5 : 1.0,
        ),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.25),
            blurRadius: 8,
            offset: const Offset(0, 2),
          ),
        ],
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Expanded(
            child: TextField(
              focusNode: _focus,
              controller: _controller,
              maxLines: null,
              minLines: 3,
              style: AppText.body.copyWith(color: AppColors.inkPrimary),
              decoration: InputDecoration(
                border: InputBorder.none,
                contentPadding: const EdgeInsets.fromLTRB(
                  AppSpacing.inner, AppSpacing.inner, AppSpacing.micro, AppSpacing.inner,
                ),
                hintText: widget.hintText,
                hintStyle: AppText.body.copyWith(color: AppColors.inkMuted),
              ),
              onSubmitted: (_) => _submit(),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 6, right: 6),
            child: GestureDetector(
              onTapDown: (_) => setState(() => _pressed = true),
              onTapCancel: () => setState(() => _pressed = false),
              onTapUp: (_) => setState(() => _pressed = false),
              onTap: _submit,
              child: AnimatedScale(
                scale: _pressed ? 0.92 : 1.0,
                duration: const Duration(milliseconds: 120),
                child: Container(
                  width: 40,
                  height: 40,
                  decoration: BoxDecoration(
                    color: widget.onSubmit != null ? AppColors.accentIce : AppColors.inkMuted,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    Icons.arrow_upward_rounded,
                    size: 20,
                    color: widget.onSubmit != null ? AppColors.bgDeep : AppColors.inkSecondary,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
