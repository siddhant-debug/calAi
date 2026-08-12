import 'package:flutter/material.dart';
import '../core/app_theme.dart';

class MealInputBar extends StatefulWidget {
  final VoidCallback? onSubmit;

  const MealInputBar({super.key, this.onSubmit});

  @override
  State<MealInputBar> createState() => _MealInputBarState();
}

class _MealInputBarState extends State<MealInputBar> {
  final _focus = FocusNode();
  bool _isFocused = false;

  @override
  void initState() {
    super.initState();
    _focus.addListener(() => setState(() => _isFocused = _focus.hasFocus));
  }

  @override
  void dispose() {
    _focus.dispose();
    super.dispose();
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
              maxLines: null,
              minLines: 3,
              style: AppText.body.copyWith(color: AppColors.inkPrimary),
              decoration: InputDecoration(
                border: InputBorder.none,
                contentPadding: const EdgeInsets.fromLTRB(
                  AppSpacing.inner, AppSpacing.inner, AppSpacing.micro, AppSpacing.inner,
                ),
                hintText: 'What did you eat?',
                hintStyle: AppText.body.copyWith(color: AppColors.inkMuted),
              ),
            ),
          ),
          Padding(
            padding: const EdgeInsets.only(bottom: 6, right: 6),
            child: GestureDetector(
              onTap: widget.onSubmit,
              child: Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: widget.onSubmit != null
                      ? AppColors.accentIce
                      : AppColors.inkMuted,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Icon(
                  Icons.arrow_upward_rounded,
                  size: 20,
                  color: widget.onSubmit != null
                      ? AppColors.bgDeep
                      : AppColors.inkSecondary,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
