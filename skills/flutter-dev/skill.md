---
name: flutter-dev
description: >
  Implement Flutter files for the calAI frontend. Use when the user says "implement",
  "build", "code", "write the", or "work on" any of the calai_frontend files — models,
  providers, screens, widgets, services, or main.dart. Also trigger on "wire up",
  "add the router", "make onboarding work", "build the home screen", or any
  feature-level request for the Flutter app.
---

# calAI Flutter Dev Skill

You are implementing the calAI Flutter iOS frontend. Read this entire file before writing
any code — it is both the technical spec and the design system.

---

## Project location

`calai_frontend/` (sibling to `calai_backend/`)

---

## Implementation order

Always follow this sequence. Never skip ahead.

1. `lib/models/user_profile.dart`
2. `lib/models/meal_entry.dart`
3. `lib/core/storage_service.dart`
4. `lib/core/api_service.dart`
5. `lib/providers/user_provider.dart`
6. `lib/providers/meal_provider.dart`
7. `lib/widgets/day_ring.dart`
8. `lib/widgets/meal_input_bar.dart`
9. `lib/screens/onboarding_screen.dart`
10. `lib/screens/home_screen.dart`
11. `lib/main.dart` (router + ProviderScope — always last)

---

## Technical facts

**Backend base URL:** `http://<LOCAL_IP>:8000/api`
Tell the user to replace `<LOCAL_IP>` with their Mac's LAN IP (required for real device + simulator).
**Backend run command:** `uvicorn calai_backend.main:app --reload --host 0.0.0.0`

**API calls:**
- `POST /api/calculate` → body matches `UserProfile.toJson()`, returns `bmr_kcal`, `tdee_kcal`, `calorie_goal_kcal`
- `POST /api/parse-meal` → `{"text": "<meal description>"}`, returns `items[]`, `total_kcal`

**State management:** Riverpod (`flutter_riverpod ^2.5.1`) — use `StateNotifierProvider` for user profile + meals

**Storage:** SharedPreferences keys:
- `"user_profile"` (JSON)
- `"calorie_goal"` (double)
- `"meals_YYYY-MM-DD"` (JSON list)

**Navigation:** go_router — `/` redirects to `/onboarding` (no profile) or `/home` (has profile)

**Day ring colour logic:**
```
progress = (day_total_kcal / calorie_goal).clamp(0.0, 1.0)
grey:  progress < 0.80
green: 0.80 – 1.00
amber: 1.00 – 1.15
red:   > 1.15
```
Animate with `AnimationController`, 300 ms ease-in-out.
Today's ring gets a highlight shadow.

---

## Design system — read this and follow it exactly

### Philosophy

calAI is a precision tool for people who care about their body as a system. The visual
language should feel like a high-end sports chronograph, not a wellness pastel app.
Dark, dense, exact. Every number is legible at a glance. Colour carries signal, not
decoration. The single signature element is the **Day Ring** — a custom arc that
shifts colour as fuel fills.

### Colour tokens

Use these exact values. Define them as static constants in `lib/core/app_theme.dart`.

```dart
// Backgrounds
static const Color bgDeep    = Color(0xFF0D0D0F); // near-black, main scaffold
static const Color bgCard    = Color(0xFF1A1A1F); // card surfaces
static const Color bgSurface = Color(0xFF222228); // input fields, chips

// Ink
static const Color inkPrimary   = Color(0xFFF0F0F4); // headlines, large numbers
static const Color inkSecondary = Color(0xFF8A8A96); // labels, captions
static const Color inkMuted     = Color(0xFF45454F); // dividers, placeholders

// Signal — ring + status colours
static const Color signalGreen = Color(0xFF3EE88B); // 80–100 % zone
static const Color signalAmber = Color(0xFFFFB830); // 100–115 % zone
static const Color signalRed   = Color(0xFFFF4757); // > 115 % zone
static const Color signalGrey  = Color(0xFF3A3A44); // < 80 % zone (ring empty)

// Accent — used sparingly, one interactive highlight
static const Color accentIce   = Color(0xFF6FECFF); // tappable elements, focus rings
```

Never use any colour not in this list. No white (#FFFFFF) — use `inkPrimary`. No black
(#000000) — use `bgDeep`.

### Typography

Define a `TextTheme` extension. Use **DM Mono** for all numerics/data. Use **Inter**
for all labels, body, and UI copy. Import both via `google_fonts`.

```dart
// Display number — calorie total, big ring number
static TextStyle get numDisplay => GoogleFonts.dmMono(
  fontSize: 52, fontWeight: FontWeight.w600,
  color: AppColors.inkPrimary, letterSpacing: -1.5,
);

// Section number — meal kcal, macro values
static TextStyle get numSection => GoogleFonts.dmMono(
  fontSize: 22, fontWeight: FontWeight.w500,
  color: AppColors.inkPrimary, letterSpacing: -0.5,
);

// Small data — timestamps, item kcal
static TextStyle get numSmall => GoogleFonts.dmMono(
  fontSize: 13, fontWeight: FontWeight.w400,
  color: AppColors.inkSecondary,
);

// UI label — button text, field labels
static TextStyle get labelLg => GoogleFonts.inter(
  fontSize: 15, fontWeight: FontWeight.w600,
  color: AppColors.inkPrimary, letterSpacing: 0.1,
);

static TextStyle get labelSm => GoogleFonts.inter(
  fontSize: 12, fontWeight: FontWeight.w500,
  color: AppColors.inkSecondary, letterSpacing: 0.4,
  // use .toUpperCase() on the string for caps labels
);

// Body — onboarding copy, empty states
static TextStyle get body => GoogleFonts.inter(
  fontSize: 15, fontWeight: FontWeight.w400,
  color: AppColors.inkSecondary, height: 1.55,
);
```

### Spacing & shape

```
Base unit: 8px
Micro gap:      4px  (between label + value in same row)
Inner padding: 16px  (card interior, list item padding)
Section gap:   24px  (between cards)
Screen edge:   20px  (horizontal page padding)

Border radius:
  card:   12px
  input:  10px
  chip:    6px
  button: 10px  (NOT pill-shaped)

Dividers: 1px, colour inkMuted, no opacity tricks
```

### Component patterns

**Cards** — `bgCard`, radius 12, no border, subtle inner shadow:
```dart
BoxDecoration(
  color: AppColors.bgCard,
  borderRadius: BorderRadius.circular(12),
  boxShadow: [BoxShadow(color: Colors.black38, blurRadius: 8, offset: Offset(0, 2))],
)
```

**Inputs / MealInputBar** — `bgSurface`, radius 10, `inkMuted` hint, `accentIce` focus
border (1.5px):
```dart
// focused border:
Border.all(color: AppColors.accentIce, width: 1.5)
// unfocused border:
Border.all(color: AppColors.inkMuted, width: 1.0)
```

**Primary button** — `accentIce` background, `bgDeep` text, radius 10, height 52,
`labelLg` style. Never use `ElevatedButton` defaults — always build with `GestureDetector`
+ `AnimatedContainer` for a 0.95 scale press animation.

**Chips (meal items)** — `bgSurface` background, `inkSecondary` text, no border.
Show item name + kcal in `numSmall`. Horizontal scroll row.

**Bottom sheet** — `bgCard` background, drag handle in `inkMuted`, radius 20 top only.

### Day ring (the signature element)

The ring lives in `lib/widgets/day_ring.dart` as a `CustomPainter`.

- **Track arc:** full 270° (start: 135°, sweep: 270°), colour `signalGrey`, stroke 10px,
  `StrokeCap.round`
- **Fill arc:** same geometry, colour interpolated based on zone, same stroke width
- **Centre content:** stacked `numDisplay` kcal eaten + `labelSm` "KCAL" in caps
- **Glow:** today's ring only gets a `BoxShadow` using the current zone colour at 30%
  opacity, blur 20px — gives the impression the ring is emitting light
- **Size:** 200px diameter on home screen, 100px on history cells

Zone colour interpolation — do NOT just snap between colours. Lerp smoothly:
```dart
Color _ringColor(double progress) {
  if (progress < 0.80) return AppColors.signalGrey;
  if (progress <= 1.00) return Color.lerp(AppColors.signalGrey, AppColors.signalGreen, (progress - 0.8) / 0.2)!;
  if (progress <= 1.15) return Color.lerp(AppColors.signalGreen, AppColors.signalAmber, (progress - 1.0) / 0.15)!;
  return Color.lerp(AppColors.signalAmber, AppColors.signalRed, ((progress - 1.15) / 0.10).clamp(0.0, 1.0))!;
}
```

### Onboarding screen

Minimal. Dark background. One field per step (paged, not scrolled). Progress shown as
a row of 4 small `inkMuted`/`accentIce` dots — no text like "Step 1 of 4". Each page:
large `numDisplay`-style prompt (e.g. "How old\nare you?") + single input + next button.
No decorative illustrations. The austerity is the design.

### Home screen layout (top → bottom)

```
StatusBar (dark icons)
─────────────────────────
[20px h-pad]
"Today"                    ← labelSm uppercase, inkSecondary
[4px gap]
[Day Ring — centred, 200px]   ← today's ring with glow
[8px gap]
Goal: 2 340 kcal           ← numSmall, inkSecondary, monospace
─────────────────────────
[24px gap]
"MEALS"                    ← labelSm uppercase, inkSecondary
[12px gap]
[MealCard list — scroll]
─────────────────────────
[Floating MealInputBar]    ← sticks above keyboard
```

**MealCard:** bgCard, 16px padding, meal description in `labelLg`, kcal in `numSection`
right-aligned, timestamp in `numSmall` below description. Meal item chips in horizontal
scroll below.

### Empty state

No art. Just:
```
numSection  "Nothing logged yet."
body        "Type what you ate below."
```
Centred vertically in the meal list area.

### Micro-interactions

- MealInputBar send button: scale 0.92 on press, 120ms, then back
- MealCard appear: `FadeTransition` + `SlideTransition` (from y+20 → y+0), 200ms staggered
  by index (delay = index * 40ms)
- Ring fill change: `AnimationController` 300ms `Curves.easeInOut`

---

## Coding rules

- No comments unless the WHY is non-obvious
- No error handling for impossible cases — only validate at API boundary (null checks on
  JSON responses)
- Keep widgets small; extract `CustomPainter` to `day_ring.dart` only
- Run `flutter analyze` after each file; fix all errors before moving on
- After implementing a screen, run on simulator and confirm the golden path works
- Never use `Colors.white`, `Colors.black`, `Colors.blue`, or any `Colors.*` constant —
  always use `AppColors.*`
- Never use default `ThemeData` button styles — always compose manually
- `google_fonts` must be the only font source; no asset fonts

---

## After each file

```bash
cd calai_frontend && flutter analyze lib/<file>
```

Fix any errors before proceeding.
Update the session memory implementation state table:

| File | Status | Notes |
|------|--------|-------|
| models/user_profile.dart | ⬜ | |
| models/meal_entry.dart   | ⬜ | |
| core/storage_service.dart| ⬜ | |
| core/api_service.dart    | ⬜ | |
| providers/user_provider.dart | ⬜ | |
| providers/meal_provider.dart | ⬜ | |
| widgets/day_ring.dart    | ⬜ | |
| widgets/meal_input_bar.dart | ⬜ | |
| screens/onboarding_screen.dart | ⬜ | |
| screens/home_screen.dart | ⬜ | |
| main.dart                | ⬜ | |

Legend: ⬜ pending · 🔄 in progress · ✅ done · ❌ error