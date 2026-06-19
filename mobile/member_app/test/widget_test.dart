import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:smartclub_member/main.dart';

void main() {
  testWidgets('empty state renders its message', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: EmptyState('Aucune donnee disponible.'),
        ),
      ),
    );

    expect(find.text('Aucune donnee disponible.'), findsOneWidget);
  });
}
