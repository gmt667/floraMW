import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:floramw/main.dart';
import 'package:floramw/store.dart';
import 'package:floramw/models.dart';
import 'package:floramw/localization.dart';
import 'package:floramw/screens/profile.dart';
import 'package:floramw/screens/translations.dart';

Future<void> loadFonts() async {
  final loader = FontLoader('FloraSans');
  loader.addFont(rootBundle.load('assets/fonts/Roboto-Regular.ttf'));
  loader.addFont(rootBundle.load('assets/fonts/Roboto-Bold.ttf'));
  await loader.load();
  final icons = FontLoader('MaterialIcons');
  icons.addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
  await icons.load();
  await TranslationCatalog.load();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(loadFonts);
  Future<AppStore> store() async {
    SharedPreferences.setMockInitialValues({'onboarding': true});
    return AppStore(await SharedPreferences.getInstance());
  }

  Widget shell(AppStore s, Widget child) => MaterialApp(
    theme: ThemeData(useMaterial3: true, fontFamily: 'FloraSans'),
    builder: (context, c) => FloraScope(
      store: s,
      child: MediaQuery(
        data: MediaQuery.of(context).copyWith(textScaler: TextScaler.linear(2)),
        child: c!,
      ),
    ),
    home: child,
  );
  testWidgets('home navigation handles narrow screen and large text', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final s = await store();
    s.largeText = true;
    await tester.pumpWidget(FloraMWApp(store: s));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    for (final label in ['Identify', 'My garden', 'Settings', 'Discover']) {
      await tester.tap(find.text(label).last);
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull, reason: label);
    }
  });
  testWidgets('profile handles large text and source sections', (tester) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final s = await store();
    await tester.pumpWidget(
      shell(s, ProfileScreen(plant: plants.first, store: s)),
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    await tester.scrollUntilVisible(
      find.text('Sources & image credit'),
      300,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  testWidgets('translation review remains scrollable with large text', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(320, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final s = await store();
    await tester.pumpWidget(shell(s, TranslationScreen(store: s)));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
  });
  test('local translation edits persist and can be removed', () async {
    final s = await store();
    await s.setTranslation('yao', 'Settings', 'Local review wording');
    final loaded = AppStore(await SharedPreferences.getInstance());
    expect(
      loaded.translationOverrides['yao']?['Settings'],
      'Local review wording',
    );
    await loaded.setTranslation('yao', 'Settings', '');
    expect(loaded.translationOverrides['yao']?['Settings'], isNull);
    await loaded.setTranslation('tum', 'Settings', 'Local draft');
    await loaded.clearPersonalData();
    expect(loaded.translationOverrides, isEmpty);
  });
  testWidgets(
    'discover controls expose labels and adequate Android tap targets',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final semantics = tester.ensureSemantics();

      final s = await store();
      await tester.pumpWidget(FloraMWApp(store: s));
      await tester.pumpAndSettle();
      await expectLater(tester, meetsGuideline(labeledTapTargetGuideline));
      await expectLater(tester, meetsGuideline(androidTapTargetGuideline));
      semantics.dispose();
    },
  );
  test(
    'legacy language preferences migrate to Malawi-specific packs',
    () async {
      SharedPreferences.setMockInitialValues({
        'floramw_state': jsonEncode({
          'language': 'seh',
          'translations': {
            'seh': {'Settings': 'Local draft'},
          },
        }),
      });
      final s = AppStore(await SharedPreferences.getInstance());
      expect(s.language, 'swk');
      expect(s.translationOverrides['swk']?['Settings'], 'Local draft');
    },
  );
}
