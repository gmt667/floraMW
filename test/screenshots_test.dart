import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:floramw/main.dart';
import 'package:floramw/models.dart';
import 'package:floramw/services/api_client.dart';
import 'package:floramw/services/sync_service.dart';
import 'package:floramw/store.dart';
import 'layout_test.dart' show loadFonts;

/// Minimal HTTP stub for golden screenshot tests.
///
/// Returns synthetic but deterministic API responses so that [DiscoverScreen]
/// always loads the full catalogue without hitting a real server or showing
/// the offline-notice banner. Every screenshot is therefore pixel-stable.
http.Client _screenshotMockClient() {
  final plantsJson = plants
      .map(
        (p) => {
          'id': p.id,
          'name': p.name,
          'scientific': p.scientific,
          'family': p.family,
          'category': p.category,
          'symbol': p.symbol,
          'description': p.description,
        },
      )
      .toList();

  return MockClient((request) async {
    // Token bootstrap
    if (request.url.path == '/api/v1/auth/anonymous' &&
        request.method == 'POST') {
      return http.Response(
        jsonEncode({
          'device_token': 'screenshot-test-token',
          'token_type': 'bearer',
          'role': 'guest',
          'is_anonymous': true,
        }),
        201,
        headers: {'content-type': 'application/json'},
      );
    }
    // Flower catalogue
    if (request.url.path == '/api/v1/flowers' && request.method == 'GET') {
      return http.Response(
        jsonEncode({
          'items': plantsJson,
          'total': plantsJson.length,
          'page': 1,
          'pages': 1,
        }),
        200,
        headers: {'content-type': 'application/json'},
      );
    }
    return http.Response('Not found', 404);
  });
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUpAll(loadFonts);

  Future<AppStore> prepare(WidgetTester tester) async {
    await tester.binding.setSurfaceSize(const Size(390, 844));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    SharedPreferences.setMockInitialValues({'onboarding': true});
    final prefs = await SharedPreferences.getInstance();
    final mockClient = _screenshotMockClient();
    final apiClient = FloraApiClient(
      httpClient: mockClient,
      baseUrl: 'http://127.0.0.1:8000',
      prefs: prefs,
    );
    final syncService = SyncService(client: apiClient, prefs: prefs);
    final s = AppStore(prefs, syncService: syncService);
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
    await tester.runAsync(() async {
      final element = tester.element(find.byType(Scaffold).first);
      await precacheImage(
        const AssetImage('assets/plants/hibiscus.jpg'),
        element,
      );
    });
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(Scaffold).first,
      matchesGoldenFile('../docs/screenshots/profile.png'),
    );
  });
}
