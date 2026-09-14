import 'package:flutter/material.dart';
import '../core/app_theme.dart';

/// The "paper line" input used by both the diary (`home_screen.dart`) and
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

  void _submit(String _) {
    final text = _controller.text.trim();
    if (text.isEmpty || widget.onSubmit == null) return;
    widget.onSubmit!(text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      height: 36,
      decoration: BoxDecoration(
        border: Border(
          bottom: BorderSide(
            color: _isFocused ? AppColors.accentIce : AppColors.inkMuted,
            width: 1.0,
          ),
        ),
      ),
      alignment: Alignment.centerLeft,
      child: TextField(
        focusNode: _focus,
        controller: _controller,
        style: AppText.body.copyWith(color: AppColors.inkPrimary),
        maxLines: 1,
        textInputAction: TextInputAction.send,
        onSubmitted: _submit,
        decoration: InputDecoration(
          border: InputBorder.none,
          isDense: true,
          contentPadding: EdgeInsets.zero,
          hintText: widget.hintText,
          hintStyle: AppText.body.copyWith(color: AppColors.inkMuted),
        ),
      ),
    );
  }
}
