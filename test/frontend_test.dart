import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:floramw/main.dart';
import 'package:floramw/models.dart';
import 'package:floramw/store.dart';
import 'package:floramw/locale_data.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test("all 28 districts and seven language choices", () {
    expect(allDistricts.length, 28);
    expect(allDistricts.toSet().length, 28);
    expect(
      languageNames.values,
      containsAll([
        "English",
        "Chichewa",
        "Yao",
        "Tumbuka",
        "Sena",
        "Lhomwe",
        "Tonga",
      ]),
    );
  });
  Future<AppStore> makeStore() async {
    SharedPreferences.setMockInitialValues({'onboarding': true});
    return AppStore(await SharedPreferences.getInstance());
  }

  test(
    'bookmarks, journal notes and settings survive store reconstruction',
    () async {
      final s = await makeStore();
      await s.toggleSave('hibiscus');
      await s.addDiscovery('hibiscus', null);
      s.history.first.note = 'Observed in a garden';
      s.dark = true;
      await s.commit();
      final reloaded = AppStore(await SharedPreferences.getInstance());
      expect(reloaded.saved, contains('hibiscus'));
      expect(reloaded.history.first.note, 'Observed in a garden');
      expect(reloaded.dark, true);
      await reloaded.clearPersonalData();
      final cleared = AppStore(await SharedPreferences.getInstance());
      expect(cleared.saved, isEmpty);
      expect(cleared.history, isEmpty);
      expect(cleared.dark, true);
    },
  );
  test('demo distinguishes unknown and service failure', () async {
    final service = DemoIdentificationService();
    expect(
      (await service.identify(null, DemoOutcome.noMatch)).candidateIds,
      isEmpty,
    );
    await expectLater(
      service.identify(null, DemoOutcome.error),
      throwsException,
    );
    expect(
      (await service.identify('unrelated.jpg', DemoOutcome.matches)).isDemo,
      true,
    );
  });
  testWidgets('search resets and demo no-match can be retried', (tester) async {
    final s = await makeStore();
    await tester.pumpWidget(FloraMWApp(store: s));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'not-a-flower');
    await tester.pumpAndSettle();
    expect(find.text('No plants found'), findsOneWidget);
    await tester.ensureVisible(find.text('Reset filters'));
    await tester.tap(find.text('Reset filters'));
    await tester.pumpAndSettle();
    expect(find.text('No plants found'), findsNothing);
    await tester.tap(find.text('Identify').last);
    await tester.pumpAndSettle();
    final dropdown = find.byType(DropdownButtonFormField<DemoOutcome>);
    await tester.ensureVisible(dropdown);
    await tester.tap(dropdown);
    await tester.pumpAndSettle();
    await tester.tap(find.text('No match').last);
    await tester.pumpAndSettle();
    final run = find.text('Explore demo without a photo');
    await tester.ensureVisible(run);
    await tester.tap(run);
    await tester.pump();
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    await tester.pumpAndSettle(const Duration(seconds: 2));
    await tester.ensureVisible(find.text('No match found'));
    expect(find.text('No match found'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('welcome can be completed and persists', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final s = AppStore(await SharedPreferences.getInstance());
    await tester.pumpWidget(FloraMWApp(store: s));
    await tester.pumpAndSettle();
    expect(find.text('Meet FloraMW.'), findsOneWidget);
    await tester.tap(find.text('Skip'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Choose your district'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byType(TextField).first, 'Rumphi');
    await tester.pumpAndSettle();
    await tester.tap(find.text('Rumphi').last);
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.text('Save preferences & explore'));
    await tester.tap(find.text('Save preferences & explore'));
    await tester.pumpAndSettle();
    expect(s.district, 'Rumphi');
    expect(s.onboarding, true);
    expect(find.text('ROOTED IN MALAWI'), findsOneWidget);
  });
}
