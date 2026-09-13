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

Retired: `lib/widgets/day_ring.dart` (the ring is gone — see "Status strip", not a ring, is
the new signature element). Suggested breakdown below; the exact file split is
`flutter-engineer`'s call, this is guidance, not a contract.

1. `lib/models/user_profile.dart` — now holds a partially-filled profile shape (slot-filling)
2. `lib/models/meal_entry.dart` — now needs a status field: `pending | logged | error` (see
   "Entry card" states)
3. `lib/core/storage_service.dart`
4. `lib/core/api_service.dart` — add the `/api/agent` call (contract shape is ADR-007's job,
   not this spec's)
5. `lib/providers/user_provider.dart`
6. `lib/providers/meal_provider.dart` — now session-scoped (keyed by date)
7. `lib/widgets/meal_input_bar.dart`
8. `lib/widgets/agent_message.dart` — new: renders the agent's rare spoken lines (slot-filling
   question, confirmation, weekly weight check-in)
9. `lib/widgets/entry_card.dart` — new: replaces the old inline `MealCard`, handles all three
   states (pending/logged/error)
10. `lib/widgets/status_strip.dart` — new: the hero kcal number + accent line + macro row
11. `lib/widgets/history_sheet.dart` — new: the bottom sheet for past-day navigation
12. `lib/screens/onboarding_screen.dart` — now a single conversational thread, not a `PageView`
13. `lib/screens/home_screen.dart` — today's diary/session screen
14. `lib/main.dart` (router + ProviderScope — always last)

---

## Technical facts

**Backend base URL:** `http://<LOCAL_IP>:8000/api`
Tell the user to replace `<LOCAL_IP>` with their Mac's LAN IP (required for real device + simulator).
**Backend run command:** `uvicorn calai_backend.main:app --reload --host 0.0.0.0`

**API calls:**
- `POST /api/calculate` → body matches `UserProfile.toJson()`, returns `bmr_kcal`, `tdee_kcal`, `calorie_goal_kcal`
- `POST /api/parse-meal` → `{"meal_text": "<meal description>", "meal_type": "breakfast|lunch|dinner|snack"}`
  (`meal_type` optional, defaults to `snack`). Returns `items[]` where each item is
  `{name, quantity, unit, calories_kcal, protein_g, carbs_g, fat_g, confidence}` plus
  `total_kcal`, `meal_type`, `model_latency_ms`.
  **The field is `meal_text`, not `text`** — sending `text` returns HTTP 422.
- `POST /api/agent` → now **required** by conversational onboarding, profile updates,
  recommendations, and the weekly weight check-in. It is not called for a plain meal log — that
  goes straight to `/api/parse-meal` and logs silently (see "Log silently"). Today it returns
  prose only; a structured response contract is ADR-007's job
  (`plans/v1-product-brief.md` "Needs an ADR" item 2), not this spec's — this spec describes
  what the response must be able to render (a slot-filling question, a profile-confirmation
  payload, a recommendation, a weight check-in prompt) without inventing its JSON shape.

**State management:** Riverpod 3 (`flutter_riverpod ^3.4.3`) — use `Notifier` / `AsyncNotifier`
(**not** `StateNotifierProvider`, which is the Riverpod 2 API). Expose `AsyncValue` so screens
can render loading / error / data states — required because `/api/parse-meal` takes 9–40s (see
"Entry card" pending state below, which replaces the old bare enabled/disabled input bar).

**Storage:** persistence model (client-side `SharedPreferences` vs server-side) is an **open
architecture decision**, not a UI one — deferred to ADR-007
(`plans/v1-product-brief.md` "Needs an ADR" item 1). These screens are written against provider
state, not a specific storage backend, so they don't block on this. Whatever the ADR picks, the
shapes providers must expose are: a profile (possibly partial, mid-slot-filling), per-date
sessions of entries, a weight-history list, and the last weekly-check-in timestamp.

**Navigation:** go_router — `/` redirects to `/onboarding` (no profile) or `/home` (has profile).
`/home` is today's session by default; opening a past day via the history sheet is an in-place
session swap on the same route, not a new route per date — reinforces "open a different day's
session," not "leave the app's one screen."

**Profile is captured conversationally at onboarding** (one free-text message, agent extracts
what it can, asks only for what's missing, one confirm step before it locks in) and can be
partial mid-flow — see "Onboarding screen" below. `UserProfile` must be able to represent a
partially-filled state during onboarding; no screen *after* onboarding's confirm step needs to
handle a partial profile.

---

## Decisions pending

The v1 product pivot (`plans/v1-product-brief.md`, resolved with the user 2026-09-13) closed
almost every row of the old USER-DECIDES table below by settling the product behaviour; this
UI spec then resolved the remaining UI-shape questions. Two items are genuinely still open —
both are architecture/backend contract questions, not UI questions, and don't block
`flutter-engineer` building the screens described below against mocked/placeholder provider
state.

| # | Open question | Status |
|---|---|---|
| 1 | `POST /api/agent` structured response contract | **Open — ADR-007's job.** This spec (below) describes what the UI must be able to render from it (slot-filling question, profile confirmation, recommendation, weekly check-in prompt); it does not define the JSON shape. `architecture-designer` owns this next. |
| 2 | Persistence model — client-side vs server-side | **Open — ADR-007's job.** Screens are written against provider state, storage-backend-agnostic. |

Resolved by this spec (previously rows 1–5 of the old table):

| # | Old question | Resolution |
|---|---|---|
| 1 | Multi-item rendering | One card per submission (raw text + `total_kcal` + timestamp), one chip per parsed item below it. Swipe-to-delete removes the whole entry, not individual items — item-level correction goes through chat ("remove the dal"), per the brief. See "Entry card." |
| 2 | Nutrition detail shown | kcal total (hero), aggregate macros in the status strip (not per-entry), plus a single low-confidence marker per item chip. Full per-item macros are not shown on the card — one accessory (confidence), not three (macros + confidence + meal-type chip). See "Entry card" and "Status strip." |
| 3 | Day-ring range | Moot — the ring is retired. Today's totals live in the status strip; every other day is reachable through the history sheet, not a fixed weekday row. |
| 4 | `meal_type` affordance | Inferred from clock, shown as quiet read-only metadata on the entry card (never a picker or chip row), agent may override from text. Per the brief, the user is never asked to pick one. |
| 5 | In-flight state for 9–40s calls | Optimistic pending entry card with an indeterminate accentIce sweep bar — see "Entry card, pending state." Input bar itself stays enabled during a send (supports logging a second entry while the first is still in flight). |

---

## Design system — read this and follow it exactly

### Philosophy

calAI is a precision tool for people who care about their body as a system. The visual
language should feel like a high-end sports chronograph, not a wellness pastel app.
Dark, dense, exact. Every number is legible at a glance. Colour carries signal, not
decoration.

As of the v1 product pivot (`plans/v1-product-brief.md`), the app is a quiet per-day diary,
not a dashboard — the signature element is no longer a graphic ring. The equivalent move is
the **status strip's hero number**: today's kcal-eaten figure rendered in `numDisplay`, its
colour alone carrying the zone signal (grey/green/amber/red — see "Zone colour signal"
below). One number, colour-coded, is the whole signature; everything else in the strip is
intentionally quieter than it.

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

### Zone colour signal

Retired the ring; kept the maths, because the zone thresholds are a proven, load-bearing part
of the visual language — reused wherever a kcal figure needs a colour signal (status strip
hero number, status strip accent line, history sheet per-day dots).

```dart
Color zoneColor(double progress) {
  if (progress < 0.80) return AppColors.signalGrey;
  if (progress <= 1.00) return Color.lerp(AppColors.signalGrey, AppColors.signalGreen, (progress - 0.8) / 0.2)!;
  if (progress <= 1.15) return Color.lerp(AppColors.signalGreen, AppColors.signalAmber, (progress - 1.0) / 0.15)!;
  return Color.lerp(AppColors.signalAmber, AppColors.signalRed, ((progress - 1.15) / 0.10).clamp(0.0, 1.0))!;
}
// progress = (day_total_kcal / calorie_goal_kcal).clamp(0.0, 1.0 or above — do not clamp the
// upper bound for colour purposes, only for any width/fill maths, so > 115% still reads red)
```

Where a colour transition happens on-screen (status strip number updating live as entries log),
animate the `Color.lerp` over 300ms `Curves.easeInOut` — same feel as the old ring, minus the
arc.

### Onboarding screen (conversational)

Retired: the 4-step `PageView` (age → weight/height → activity → goal/rate) and its 4-dot
progress indicator. Onboarding is now a single scrolling thread, visually the same
component family as the diary screen below (status bar, `bgDeep`, `MealInputBar` fixed at the
bottom) — deliberately, since onboarding *is* the first exchange in what the brief calls "a
fresh chat thread," not a separate wizard.

**First launch (empty state):** mostly whitespace — the austerity is the design, carried over
from the old spec's instinct even though the mechanism changed. Content block vertically
centred in the space above the input bar:
- Headline: `labelLg`, `inkPrimary` — "Tell me about yourself and your goal."
- One line below, `body` (`inkSecondary`): an example in quotes, e.g. *"I'm 60kg, want to gain
  8kg over 4 months, get stronger, eat clean, not force-fed."* — teaches the free-text
  affordance without a form.
- `MealInputBar` at the bottom, same visual spec as the diary screen's input bar, placeholder
  swapped to "Tell me about yourself…".

**Two message roles render in the thread** (new pattern, needed because — unlike daily
logging, which is silent — onboarding must ask follow-up questions and show a confirmation):
- **User message:** plain text, no card, no background — just the page. `labelLg`,
  `inkPrimary`. Left-aligned, full width, sits directly on `bgDeep`.
- **Agent message:** `bgCard` card, radius 12, 16px padding (standard Card pattern), `body`
  style throughout (`inkSecondary`) — deliberately quieter than the user's own words. This is
  the visual expression of "the app speaks rarely and never louder than the user."
  `8px` gap above, following the user message it replies to.

**Slot-filling question** (a required field is missing): renders as a plain agent message —
`body` text, e.g. "What's your height?" No structure, just a question. User answers via the
input bar as a new user message; loop continues until nothing required is missing.

**Confirmation step** (all required fields present): renders as a structured agent message
(`bgCard`, 16px padding):
```
PROFILE                          ← labelSm uppercase, inkSecondary
Weight            60 kg          ← labelSm tag (left) / numSmall value (right), one row per field
Goal              Gain 8kg / 4mo
Activity          Moderate
Height            172 cm
─────────────────────────        ← 1px divider, inkMuted
Daily target      2,340 kcal     ← numSection, inkPrimary — the one emphasised number, the
                                    single output of the whole exchange
[8px gap]
[Confirm — primary button, full width]
"Or just tell me what's wrong."  ← body, inkMuted, centred below the button
```
One button only, by design (restraint: a second "Edit" button competing with "Confirm" is an
accessory this screen doesn't need) — correcting a wrong field is the same chat-correction
pattern used everywhere else in the app ("reply to fix it"), not a separate UI mode.
`Confirm` fires `POST /api/calculate` and locks the profile.

### Today screen (diary session) — layout top → bottom

```
StatusBar (dark icons)
─────────────────────────
[20px h-pad]
"TODAY · SEP 13"  ⌄        ← labelSm uppercase, inkSecondary, tappable → opens History sheet
[8px gap]
[Status strip]              ← see below
─────────────────────────  ← 1px divider, inkMuted
[24px gap]
"ENTRIES"                   ← labelSm uppercase, inkSecondary
[12px gap]
[Entry feed — scrolls, oldest at top, newest appended
 at the bottom just above the input bar, like a chat log;
 auto-scrolls to bottom on new entry]
─────────────────────────
[Floating MealInputBar]    ← sticks above keyboard, always enabled (a second entry can be
                              sent while an earlier one is still in flight)
```

Opening a past day (via the history sheet) swaps the same screen's data to that date — the
header becomes e.g. "SEP 12 · FRI" and loses the live "today" framing, but the layout,
status strip, entry feed and input bar are identical; the input bar still works for
corrections on that day, per the brief's chat-correction model.

### Status strip

"Minimal but decent info," explicitly **not** a dashboard — no ring, no full-width bar per
macro. One hero number, one thin accent line (for the calorie total only), one compact macro
row. Always visible, even at zero entries (see "Empty state").

```
2,340                        ← numDisplay, colour = zoneColor(progress) — the one moment of
                                visual weight on the whole screen
of 2,600 kcal                ← numSmall, inkSecondary, directly under/beside the hero number
[4px gap]
▬▬▬▬▬▬▬▬░░░░░░              ← 2px rule, radius 1: fill = zoneColor(progress) flat,
                                width = min(progress, 1.0) × strip width; track = bgSurface
                                flat. No macro bars — this is the single bar the brief allows.
[8px gap]
P 142g · C 210g · F 68g      ← labelSm tag + numSmall value pairs, separated by an inkMuted
                                middle dot. Sums today's entries' protein_g/carbs_g/fat_g.
                                No bars, no per-macro goals shown — text only, by decision.
```

At zero entries: hero number reads "0", colour = `signalGrey` (progress 0 < 0.80), accent
line fill width 0 (flat `bgSurface` track only), macro row reads "P 0g · C 0g · F 0g".

### Entry feed & Entry card

One card per logged submission — not one row per parsed item, not an expandable tree. The
raw text + total are the entry; individual items are shown as compact chips for detail, not
as separate rows (resolves old "multi-item rendering" decision).

**Entry card, logged (success) state** — `bgCard`, radius 12, 16px padding, standard Card
pattern:
```
5 roti and a cup of dal            612           ← labelLg inkPrimary (raw text, left) /
                                                     numSection inkPrimary (total_kcal, right)
1:42 PM · lunch                                  ← numSmall inkSecondary + labelSm inkMuted
                                                     (meal_type is inferred, shown as quiet
                                                     read-only metadata — never a picker)
[● Roti · 280kcal] [Dal · 220kcal] [Rice · 112kcal]  ← chip row, horizontal scroll, bgSurface/
                                                        inkSecondary/no border/radius 6,
                                                        numSmall text
```
- Chips show item name + `calories_kcal` only — no per-item macros on the card (aggregate
  macros already live in the status strip; repeating them per item would be a second
  accessory).
- A chip gets a small leading dot (6px, `signalAmber`) **only** when that item's
  `confidence < 0.5` — the one earned accessory, justified directly by the eval baseline
  (~37% calorie MAPE, quantities are the weak spot). High-confidence items get no marker;
  the absence of a dot is the default, so the signal doesn't compete with itself.
- Swipe left reveals a delete action (`signalRed` fill, trash icon `inkPrimary`) — removes the
  whole entry. Item-level correction ("remove the dal") is a chat message, not a UI control.

**Entry card, pending (in-flight) state** — appears immediately on send, before the response
returns (round trips run 9–40s):
```
5 roti and a cup of dal
▬▬░░░░░░░░░░░░░░░░░░░░░░           ← 2px indeterminate sweep: accentIce segment (40% width)
                                       looping left→right over an inkMuted track, 1200ms linear
```
No kcal number, no chips — nothing is invented while the real value is unknown. `accentIce` is
reused here deliberately: the token's stated purpose is "tappable elements, focus rings," and
an in-flight network call is the closest thing to an active/focused process this screen has.
No shimmer/skeleton-block treatment — that reads as a wellness-app loading cliché; a single
moving line stays in the chronograph register.

**Entry card, error state** — response failed:
```
│ 5 roti and a cup of dal
│ Couldn't log — tap to retry
```
2px solid `signalRed` left border (not a full red card — stays quiet), second line in
`labelSm signalRed`. Tapping the card retries the request; swipe-to-delete still dismisses it.

### History sheet

Bottom sheet (`bgCard`, drag handle `inkMuted`, radius 20 top only — standard Bottom sheet
pattern), opened by tapping the "TODAY · SEP 13" header, ~80% screen height:
```
[drag handle]
HISTORY                              ← labelSm uppercase, inkSecondary
61.2 kg                              ← numSection, inkPrimary (latest logged weight)
vs 61.8 kg expected · week 3 of 16   ← numSmall, inkSecondary (goal-progress-over-time,
                                         deterministic math per the brief — no LLM on this path)
─────────────────────────            ← 1px divider, inkMuted
Sep 12   Fri                2,180 ●  ← numSmall date+weekday (left) / numSmall total +
Sep 11   Thu                2,610 ●    6px zoneColor dot (right), one row per past day,
Sep 10   Wed                1,950 ●    most recent first, flat list with inkMuted row dividers
...
```
Tapping a row navigates the diary screen (same component) to that date. This pattern —
dense chronological list, not a calendar grid, not a swipe gesture — is a deliberate choice:
- **Not a calendar grid:** a month grid of coloured cells is the decorative
  wellness/heatmap trope the design-critique lens flags; it also implies continuous browsing
  across a month, at odds with "each day is a separate session" — sessions are distinct,
  discrete objects reached by picking one, not squares on a continuous surface.
- **Not swipe-between-days:** a swipe gesture implies one continuous scrollable timeline,
  which blurs exactly the "separate session, like a fresh chat thread per date" boundary the
  brief specifies. A list of rows you tap into is the same information architecture as opening
  a past conversation in a chat app — matching the brief's own mental model.
The exact "on-track / behind" colour-band thresholds for the delta line are a product
call, not fixed by this spec — flag to the user/backend if not already defined by the
goal-progress math the brief describes in "Contract touchpoints."

### Empty state

No art. Status strip still renders in full (all-zero state, described above). Below the
divider, in the entries area only:
```
numSection  "Nothing logged yet."
body        "Type what you ate below."
```
Centred vertically in the entry feed area.

### Micro-interactions

- MealInputBar send button: scale 0.92 on press, 120ms, then back
- Entry card appear (logged or pending): `FadeTransition` + `SlideTransition` (from y+20 →
  y+0), 200ms, staggered by index (delay = index × 40ms) — same timing as the old MealCard
- Entry card pending → logged transition: chips and kcal number fade in, 200ms, once the
  response lands (no layout jump — reserve the kcal number's right-aligned slot from the
  pending state)
- Agent message appear: `FadeTransition` only (no slide) — quieter entrance than a user's own
  content, consistent with the "app speaks quietly" reading
- Status strip hero number colour change: `Color.lerp` over 300ms `Curves.easeInOut` (see
  "Zone colour signal")

---

## Coding rules

- No comments unless the WHY is non-obvious
- No error handling for impossible cases — only validate at API boundary (null checks on
  JSON responses)
- Keep widgets small; no `CustomPainter` widgets are needed for this spec (the ring that used
  one is retired) — flag it to `ui-engineer` before adding one
- Run `dart analyze lib/<file>` after each file; fix all errors before moving on.
  **Never `flutter analyze`** — it crashes with a missing snapshot in this install.
- After implementing a screen, run it and confirm the golden path works. iOS on-device
  debugging is currently broken (Xcode debug-session handshake); verify in Chrome
  (`flutter run -d chrome`) with DevTools' device toolbar at phone width.
- Never use `Colors.white`, `Colors.black`, `Colors.blue`, or any `Colors.*` constant —
  always use `AppColors.*`
- Colour alpha: always `.withValues(alpha: x)` — `.withOpacity()` is deprecated
- Never use default `ThemeData` button styles — always compose manually
- `google_fonts` must be the only font source; no asset fonts

---

## After each file

```bash
cd calai_frontend && dart analyze lib/<file>
```

Fix any errors before proceeding.
Update the session memory implementation state table:

| File | Status | Notes |
|------|--------|-------|
| models/user_profile.dart | ⬜ | supports partial state during onboarding |
| models/meal_entry.dart   | ⬜ | needs `pending / logged / error` status |
| core/storage_service.dart| ⬜ | persistence model pending ADR-007 |
| core/api_service.dart    | ⬜ | add `/api/agent` call, contract pending ADR-007 |
| providers/user_provider.dart | ⬜ | |
| providers/meal_provider.dart | ⬜ | session-scoped by date |
| widgets/meal_input_bar.dart | ⬜ | always-enabled during send |
| widgets/agent_message.dart | ⬜ | new |
| widgets/entry_card.dart | ⬜ | new, 3 states |
| widgets/status_strip.dart | ⬜ | new |
| widgets/history_sheet.dart | ⬜ | new |
| screens/onboarding_screen.dart | ⬜ | conversational, not PageView |
| screens/home_screen.dart | ⬜ | today's diary/session screen |
| main.dart                | ⬜ | |

Retired: `widgets/day_ring.dart` — do not implement.

Legend: ⬜ pending · 🔄 in progress · ✅ done · ❌ error