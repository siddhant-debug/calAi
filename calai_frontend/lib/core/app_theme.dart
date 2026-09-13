import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

// ─── Colour tokens ────────────────────────────────────────────────────────────
abstract final class AppColors {
  // Backgrounds
  static const Color bgDeep    = Color(0xFF0D0D0F);
  static const Color bgCard    = Color(0xFF1A1A1F);
  static const Color bgSurface = Color(0xFF222228);

  // Ink
  static const Color inkPrimary   = Color(0xFFF0F0F4);
  static const Color inkSecondary = Color(0xFF8A8A96);
  static const Color inkMuted     = Color(0xFF45454F);

  // Signal — ring + status
  static const Color signalGreen = Color(0xFF3EE88B);
  static const Color signalAmber = Color(0xFFFFB830);
  static const Color signalRed   = Color(0xFFFF4757);
  static const Color signalGrey  = Color(0xFF3A3A44);

  // Accent — interactive highlight
  static const Color accentIce = Color(0xFF6FECFF);

  /// Zone colour signal (see skills/flutter-dev/SKILL.md) — reused wherever
  /// a kcal figure needs a colour signal: status strip hero number/accent
  /// line, history sheet per-day dots. `progress` is not clamped here so
  /// >115% still reads red; clamp separately for any width/fill maths.
  static Color zoneColor(double progress) {
    if (progress < 0.80) return signalGrey;
    if (progress <= 1.00) {
      return Color.lerp(signalGrey, signalGreen, (progress - 0.80) / 0.20)!;
    }
    if (progress <= 1.15) {
      return Color.lerp(signalGreen, signalAmber, (progress - 1.00) / 0.15)!;
    }
    return Color.lerp(signalAmber, signalRed, ((progress - 1.15) / 0.10).clamp(0.0, 1.0))!;
  }
}

// ─── Text styles ──────────────────────────────────────────────────────────────
abstract final class AppText {
  static TextStyle get numDisplay => GoogleFonts.dmMono(
        fontSize: 52,
        fontWeight: FontWeight.w600,
        color: AppColors.inkPrimary,
        letterSpacing: -1.5,
      );

  static TextStyle get numSection => GoogleFonts.dmMono(
        fontSize: 22,
        fontWeight: FontWeight.w500,
        color: AppColors.inkPrimary,
        letterSpacing: -0.5,
      );

  static TextStyle get numSmall => GoogleFonts.dmMono(
        fontSize: 13,
        fontWeight: FontWeight.w400,
        color: AppColors.inkSecondary,
      );

  static TextStyle get labelLg => GoogleFonts.inter(
        fontSize: 15,
        fontWeight: FontWeight.w600,
        color: AppColors.inkPrimary,
        letterSpacing: 0.1,
      );

  static TextStyle get labelSm => GoogleFonts.inter(
        fontSize: 12,
        fontWeight: FontWeight.w500,
        color: AppColors.inkSecondary,
        letterSpacing: 0.4,
      );

  static TextStyle get body => GoogleFonts.inter(
        fontSize: 15,
        fontWeight: FontWeight.w400,
        color: AppColors.inkSecondary,
        height: 1.55,
      );
}

// ─── Spacing ──────────────────────────────────────────────────────────────────
abstract final class AppSpacing {
  static const double micro       = 4;
  static const double inner       = 16;
  static const double sectionGap  = 24;
  static const double screenEdge  = 20;
}

// ─── Themes ───────────────────────────────────────────────────────────────────
abstract final class AppTheme {
  static ThemeData get darkTheme => ThemeData(
        useMaterial3: true,
        scaffoldBackgroundColor: AppColors.bgDeep,
        colorScheme: const ColorScheme.dark(
          surface: AppColors.bgDeep,
          onSurface: AppColors.inkPrimary,
          primary: AppColors.accentIce,
          onPrimary: AppColors.bgDeep,
          secondary: AppColors.signalGreen,
        ),
        appBarTheme: AppBarTheme(
          backgroundColor: AppColors.bgDeep,
          surfaceTintColor: Colors.transparent,
          elevation: 0,
          titleTextStyle: AppText.labelLg.copyWith(fontSize: 20),
          iconTheme: const IconThemeData(color: AppColors.inkPrimary),
        ),
        listTileTheme: const ListTileThemeData(
          tileColor: AppColors.bgCard,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(12)),
          ),
          contentPadding: EdgeInsets.symmetric(
            horizontal: AppSpacing.inner,
            vertical: AppSpacing.micro,
          ),
        ),
        cardTheme: const CardThemeData(
          color: AppColors.bgCard,
          elevation: 0,
          margin: EdgeInsets.zero,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(12)),
          ),
        ),
        dividerTheme: const DividerThemeData(
          color: AppColors.inkMuted,
          thickness: 1,
          space: 1,
        ),
        textTheme: TextTheme(
          bodyMedium: AppText.body,
          bodySmall: AppText.numSmall,
          labelLarge: AppText.labelLg,
          labelSmall: AppText.labelSm,
        ),
      );

  static ThemeData get light => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: AppColors.signalGreen,
          brightness: Brightness.light,
          surface: const Color(0xFFFAFAF7),
          surfaceContainerLowest: Colors.white,
        ),
        scaffoldBackgroundColor: const Color(0xFFFAFAF7),
        appBarTheme: const AppBarTheme(
          backgroundColor: Color(0xFFFAFAF7),
          surfaceTintColor: Colors.transparent,
          elevation: 0,
          titleTextStyle: TextStyle(
            color: Color(0xFF1A1A1A),
            fontSize: 22,
            fontWeight: FontWeight.bold,
          ),
          iconTheme: IconThemeData(color: Color(0xFF1A1A1A)),
        ),
        listTileTheme: const ListTileThemeData(
          tileColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(12)),
          ),
        ),
        cardTheme: const CardThemeData(
          color: Colors.white,
          elevation: 0,
          margin: EdgeInsets.zero,
        ),
      );
}
