import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:floramw/main.dart';
import 'package:floramw/store.dart';
import 'layout_test.dart' show loadFonts;

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(loadFonts);
  Future<AppStore> prepare(WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    SharedPreferences.setMockInitialValues({'onboarding': true});
    final s = AppStore(await SharedPreferences.getInstance());
    s.district = 'Rumphi';
    return s;
  }

  testWidgets('Discover reference screenshot', (tester) async {
    final s = await prepare(tester);
    await tester.pumpWidget(FloraMWApp(store: s));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('../docs/screenshots/discover.png'),
    );
  });
  testWidgets('Identify reference screenshot', (tester) async {
    final s = await prepare(tester);
    await tester.pumpWidget(FloraMWApp(store: s));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Identify').last);
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('../docs/screenshots/identify.png'),
    );
  });
  testWidgets('Plant profile reference screenshot', (tester) async {
    final s = await prepare(tester);
    await tester.pumpWidget(FloraMWApp(store: s));
    await tester.pumpAndSettle();
    await tester.scrollUntilVisible(
      find.text('Chinese hibiscus'),
      250,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('Chinese hibiscus'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('../docs/screenshots/profile.png'),
    );
  });
}
