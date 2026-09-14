// Coverage for the "paper line" rebuild of MealInputBar: a single-line
// TextField with only a 1px bottom border (no fill, no separate submit
// button). Submission happens exclusively via the keyboard's
// TextInputAction.send -> onSubmitted callback. This is the widget's first
// dedicated test file — previously it was covered only incidentally (if at
// all) through screen-level widget tests, per flutter-engineer's handoff.

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:calai_frontend/core/app_theme.dart';
import 'package:calai_frontend/widgets/meal_input_bar.dart';

Widget _wrap(Widget child) => MaterialApp(home: Scaffold(body: child));

BoxDecoration _decorationOf(WidgetTester tester) {
  final container = tester.widget<Container>(
    find.ancestor(of: find.byType(TextField), matching: find.byType(Container)).first,
  );
  return container.decoration as BoxDecoration;
}

Color _bottomBorderColor(WidgetTester tester) {
  final decoration = _decorationOf(tester);
  return decoration.border!.bottom.color;
}

Future<void> _sendKeyboardAction(WidgetTester tester) async {
  await tester.testTextInput.receiveAction(TextInputAction.send);
  await tester.pump();
}

void main() {
  testWidgets('submitting via keyboard send action calls onSubmit with trimmed text and clears the field',
      (tester) async {
    String? submitted;

    await tester.pumpWidget(_wrap(MealInputBar(
      onSubmit: (text) => submitted = text,
    )));

    await tester.enterText(find.byType(TextField), '  two eggs and toast  ');
    await _sendKeyboardAction(tester);

    expect(submitted, 'two eggs and toast');

    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, isEmpty);
  });

  testWidgets('submitting empty text does not call onSubmit', (tester) async {
    var called = false;

    await tester.pumpWidget(_wrap(MealInputBar(
      onSubmit: (_) => called = true,
    )));

    await tester.enterText(find.byType(TextField), '');
    await _sendKeyboardAction(tester);

    expect(called, isFalse);
  });

  testWidgets('submitting whitespace-only text does not call onSubmit', (tester) async {
    var called = false;

    await tester.pumpWidget(_wrap(MealInputBar(
      onSubmit: (_) => called = true,
    )));

    await tester.enterText(find.byType(TextField), '    ');
    await _sendKeyboardAction(tester);

    expect(called, isFalse);
  });

  testWidgets('has no icon, tappable button, or GestureDetector chrome', (tester) async {
    await tester.pumpWidget(_wrap(MealInputBar(onSubmit: (_) {})));

    expect(find.byType(Icon), findsNothing);
    expect(find.byType(IconButton), findsNothing);
    expect(find.byType(ElevatedButton), findsNothing);
    expect(find.byType(TextButton), findsNothing);
    expect(find.byType(OutlinedButton), findsNothing);
    expect(find.byType(GestureDetector), findsNothing);
    expect(find.byType(InkWell), findsNothing);
  });

  testWidgets('bottom border is inkMuted when unfocused and accentIce when focused', (tester) async {
    await tester.pumpWidget(_wrap(MealInputBar(onSubmit: (_) {})));

    expect(_bottomBorderColor(tester), AppColors.inkMuted);

    await tester.tap(find.byType(TextField));
    await tester.pump();

    expect(_bottomBorderColor(tester), AppColors.accentIce);
  });
}
