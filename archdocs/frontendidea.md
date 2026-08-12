# calAI Flutter Frontend — Design Plan

## Original Idea
Full screen to write and then extract calories. Once logged, a circle for that particular day shows progress. Connect with Apple Health to track fitness / workouts.

---

## Plan: calAI Flutter Frontend (iOS)

### Context
Flutter iOS app wrapping the existing calAI FastAPI backend. Users log meals via a natural-language input bar and see weekly calorie progress as 5 circular rings (Mon–Fri). First launch triggers a setup flow that calls `/api/calculate` to establish a personal calorie goal.

---

### Folder Structure: `calai_frontend/` (sibling to `calai_backend/`)

```
calai_frontend/
├── lib/
│   ├── main.dart                   # entry, ProviderScope, router
│   ├── core/
│   │   ├── api_service.dart        # all HTTP calls (calculate + parse-meal)
│   │   └── storage_service.dart    # SharedPreferences wrapper
│   ├── models/
│   │   ├── user_profile.dart       # age/weight/height/gender/activity/goal
│   │   └── meal_entry.dart         # name, kcal, timestamp, weekday
│   ├── providers/
│   │   ├── user_provider.dart      # calorie goal + profile state (Riverpod)
│   │   └── meal_provider.dart      # today's meals + weekly totals (Riverpod)
│   ├── screens/
│   │   ├── onboarding_screen.dart  # 4-step PageView setup flow
│   │   └── home_screen.dart        # main app view
│   └── widgets/
│       ├── meal_input_bar.dart     # notebook-style text field + submit
│       └── day_ring.dart           # single circular progress ring (CustomPainter)
└── pubspec.yaml
```

---

### Dependencies
```yaml
flutter_riverpod: ^2.5.1
shared_preferences: ^2.3.1
http: ^1.2.1
go_router: ^13.2.0
intl: ^0.19.0
```

---

### API Configuration
- Base URL: `http://<LOCAL_IP>:8000/api` (user's Mac LAN IP — needed for real device + simulator)
- Backend run command: `uvicorn calai_backend.main:app --reload --host 0.0.0.0`
- Calls used:
  - `POST /api/calculate` → onboarding, returns `bmr_kcal`, `tdee_kcal`, `calorie_goal_kcal`
  - `POST /api/parse-meal` → home input bar, returns `items[]` + `total_kcal`

---

### Screen 1 — Onboarding (`onboarding_screen.dart`)
Four-step `PageView`, forward-only:

| Step | Fields | Widget |
|------|--------|--------|
| 1 | Age (int), Gender (male/female) | NumberField + SegmentedButton |
| 2 | Weight kg (float), Height cm (float) | Two NumberFields |
| 3 | Activity level (sedentary → extra_active) | 5-option vertical RadioList |
| 4 | Goal (lose/maintain/gain), Rate kg/week | DropdownButton + Slider |

On **Finish**: POST /api/calculate → store result in SharedPreferences → navigate to HomeScreen (never back to onboarding).

---

### Screen 2 — Home (`home_screen.dart`)
`Column` layout top → bottom:

**Top: Notebook Input Bar**
- `TextField` with lined/paper decoration via `CustomPaint`
- Placeholder: `"What did you eat? e.g. 2 eggs and toast"`
- Submit → `POST /api/parse-meal` → append `MealEntry` to today → persist
- Loading spinner replaces submit button; errors shown as `SnackBar`

**Middle: Today's Meal List**
- Scrollable `ListView` — meal description + kcal per entry
- Swipe-to-delete updates weekly totals

**Bottom: 5 Day Rings**
- `Row` of 5 rings, `spaceEvenly`, height 120px
- Each ring = one weekday of the current ISO week (Mon–Fri)
- Ring fill = `(total_kcal_that_day / calorie_goal_kcal).clamp(0, 1)`
- Colour: grey < 80% | green 80–100% | amber 100–115% | red > 115%
- Today's ring has a highlight shadow
- Center text: total kcal consumed that day

**`day_ring.dart` — CustomPainter:**
- Background: full grey arc
- Foreground: coloured arc, sweepAngle = 2π × progress, starts at top (−π/2)
- Animated with `AnimationController`, 300 ms ease-in-out on value change

---

### Data Persistence (`storage_service.dart`)
SharedPreferences keys:
- `"user_profile"` → JSON UserProfile
- `"calorie_goal"` → double
- `"meals_YYYY-MM-DD"` → JSON list of MealEntry

Weekly totals computed by loading Mon–Fri keys for current ISO week.

---

### Navigation (`go_router`)
```
/ → redirect → has profile? /home : /onboarding
/onboarding  → OnboardingScreen
/home        → HomeScreen
```

---

### Initialisation Steps
1. `flutter create calai_frontend --platforms=ios`
2. Add dependencies to `pubspec.yaml`, run `flutter pub get`
3. Set iOS min deployment target to 14.0 in `ios/Podfile`
4. Implement in order: models → storage_service → api_service → providers → widgets → screens → main

---

### Verification Checklist
- [ ] Backend running with `--host 0.0.0.0`
- [ ] Onboarding completes and stores `calorie_goal` in SharedPreferences
- [ ] Meal input calls `/api/parse-meal` and returns kcal
- [ ] Today's ring fills correctly after logging meals
- [ ] All 5 Mon–Fri rings render with correct colour coding
- [ ] Swipe-to-delete updates ring totals
