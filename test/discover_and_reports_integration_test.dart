import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:floramw/main.dart';
import 'package:floramw/screens/profile.dart';
import 'package:floramw/screens/settings.dart';
import 'package:floramw/services/api_client.dart';
import 'package:floramw/services/sync_service.dart';
import 'package:floramw/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('Discover Screen Backend Integration', () {
    testWidgets('loads and displays flowers from backend catalogue', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1200, 3000);
      addTearDown(tester.view.resetPhysicalSize);

      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/flowers') {
          return http.Response(
            jsonEncode({
              'total': 2,
              'page': 1,
              'limit': 100,
              'total_pages': 1,
              'has_more': false,
              'items': [
                {
                  'id': 'hibiscus',
                  'name': 'Chinese hibiscus',
                  'scientific': 'Hibiscus rosa-sinensis',
                  'family': 'Malvaceae',
                  'category': 'Garden flowers',
                  'symbol': '🌺',
                  'description': 'A tropical shrub',
                  'photo_asset': 'assets/plants/hibiscus.jpg',
                },
                {
                  'id': 'periwinkle',
                  'name': 'Madagascar periwinkle',
                  'scientific': 'Catharanthus roseus',
                  'family': 'Apocynaceae',
                  'category': 'Research interest',
                  'symbol': '🌸',
                  'description': 'A medicinal flower',
                  'photo_asset': 'assets/plants/periwinkle.jpg',
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final apiClient = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );
      final syncService = SyncService(client: apiClient, prefs: prefs);
      final store = AppStore(prefs, syncService: syncService);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DiscoverScreen(store: store, onIdentify: () {}),
          ),
        ),
      );

      // Settle async fetch
      await tester.pumpAndSettle();

      await tester.drag(find.byType(ListView), const Offset(0, -500));
      await tester.pumpAndSettle();
      expect(find.text('Chinese hibiscus'), findsOneWidget);
    });

    testWidgets('filters by query and category across backend items', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1200, 3000);
      addTearDown(tester.view.resetPhysicalSize);

      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/flowers') {
          return http.Response(
            jsonEncode({
              'total': 2,
              'page': 1,
              'limit': 100,
              'total_pages': 1,
              'has_more': false,
              'items': [
                {
                  'id': 'hibiscus',
                  'name': 'Chinese hibiscus',
                  'scientific': 'Hibiscus rosa-sinensis',
                  'family': 'Malvaceae',
                  'category': 'Garden flowers',
                  'symbol': '🌺',
                  'description': 'A tropical shrub',
                  'photo_asset': 'assets/plants/hibiscus.jpg',
                },
                {
                  'id': 'periwinkle',
                  'name': 'Madagascar periwinkle',
                  'scientific': 'Catharanthus roseus',
                  'family': 'Apocynaceae',
                  'category': 'Research interest',
                  'symbol': '🌸',
                  'description': 'A medicinal flower',
                  'photo_asset': 'assets/plants/periwinkle.jpg',
                },
              ],
            }),
            200,
            headers: {'content-type': 'application/json; charset=utf-8'},
          );
        }
        return http.Response('Not Found', 404);
      });

      final apiClient = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );
      final syncService = SyncService(client: apiClient, prefs: prefs);
      final store = AppStore(prefs, syncService: syncService);

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DiscoverScreen(store: store, onIdentify: () {}),
          ),
        ),
      );

      await tester.pumpAndSettle();

      // Enter search query matching only 'hibiscus'
      await tester.enterText(
        find.byKey(const ValueKey('catalog-search')),
        'hibiscus',
      );
      await tester.pumpAndSettle();

      expect(find.text('Chinese hibiscus'), findsOneWidget);
      expect(find.text('Madagascar periwinkle'), findsNothing);
    });

    testWidgets(
      'falls back to local reference catalogue when server is unreachable',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 3000);
        addTearDown(tester.view.resetPhysicalSize);

        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          return http.Response('Server Error', 500);
        });

        final apiClient = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final syncService = SyncService(client: apiClient, prefs: prefs);
        final store = AppStore(prefs, syncService: syncService);

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: DiscoverScreen(store: store, onIdentify: () {}),
            ),
          ),
        );

        await tester.pumpAndSettle();

        // Displays notice of local offline reference
        expect(
          find.text(
            'Server catalogue unavailable. Showing local offline reference.',
          ),
          findsOneWidget,
        );
        await tester.drag(find.byType(ListView), const Offset(0, -500));
        await tester.pumpAndSettle();
        expect(find.text('Chinese hibiscus'), findsOneWidget);
      },
    );
  });

  group('Report Submission Workflow Integration', () {
    testWidgets(
      'saves local draft independently when Save report draft is tapped',
      (tester) async {
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();
        final store = AppStore(prefs);

        await tester.pumpWidget(
          MaterialApp(
            home: ReportScreen(store: store, plantId: 'hibiscus'),
          ),
        );

        // Enter valid report content
        await tester.enterText(
          find.widgetWithText(TextFormField, 'What should be corrected?'),
          'Detailed correction notes for testing draft saving.',
        );

        // Tap 'Save report draft'
        await tester.tap(find.text('Save report draft'));
        await tester.pumpAndSettle();

        expect(store.reports.length, 1);
        expect(store.reports.first['status'], 'local-draft');
        expect(store.reports.first['plantId'], 'hibiscus');
        expect(
          store.reports.first['details'],
          'Detailed correction notes for testing draft saving.',
        );
      },
    );

    testWidgets('submits report to backend and records submitted status', (
      tester,
    ) async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-token',
      });
      final prefs = await SharedPreferences.getInstance();

      bool serverReceived = false;
      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/flowers/reports' &&
            request.method == 'POST') {
          serverReceived = true;
          return http.Response(
            jsonEncode({
              'id': 'server-report-100',
              'flower_id': 'hibiscus',
              'topic': 'Identification',
              'details': 'Flower description needs botanical citation.',
              'status': 'submitted',
              'created_at': '2026-11-17T19:35:00Z',
              'createdAt': '2026-11-17T19:35:00Z',
            }),
            201,
          );
        }
        return http.Response('Not Found', 404);
      });

      final apiClient = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );
      final syncService = SyncService(client: apiClient, prefs: prefs);
      final store = AppStore(prefs, syncService: syncService);

      await tester.pumpWidget(
        MaterialApp(
          home: ReportScreen(store: store, plantId: 'hibiscus'),
        ),
      );

      await tester.enterText(
        find.widgetWithText(TextFormField, 'What should be corrected?'),
        'Flower description needs botanical citation.',
      );

      // Tap 'Submit report'
      await tester.tap(find.text('Submit report'));
      await tester.pumpAndSettle();

      expect(serverReceived, isTrue);
      expect(store.reports.length, 1);
      expect(store.reports.first['status'], 'submitted');
      expect(store.reports.first['id'], 'server-report-100');
    });

    testWidgets(
      'preserves draft with local-draft status when server submission fails',
      (tester) async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          return http.Response('Internal Server Error', 500);
        });

        final apiClient = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final syncService = SyncService(client: apiClient, prefs: prefs);
        final store = AppStore(prefs, syncService: syncService);

        await tester.pumpWidget(
          MaterialApp(
            home: ReportScreen(store: store, plantId: 'hibiscus'),
          ),
        );

        await tester.enterText(
          find.widgetWithText(TextFormField, 'What should be corrected?'),
          'Draft will be preserved even on network error.',
        );

        await tester.tap(find.text('Submit report'));
        await tester.pumpAndSettle();

        // Preserves draft locally
        expect(store.reports.length, 1);
        expect(store.reports.first['status'], 'local-draft');
        expect(
          store.reports.first['details'],
          'Draft will be preserved even on network error.',
        );
      },
    );

    testWidgets(
      'DraftsScreen permits submitting an existing draft to backend',
      (tester) async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();

        bool serverReceived = false;
        final mockClient = MockClient((request) async {
          if (request.url.path == '/api/v1/flowers/reports' &&
              request.method == 'POST') {
            serverReceived = true;
            return http.Response(
              jsonEncode({
                'id': 'draft-submitted-200',
                'topic': 'Plant care',
                'details': 'Pruning advice needs review for Zomba region.',
                'status': 'submitted',
                'created_at': '2026-11-17T19:35:00Z',
                'createdAt': '2026-11-17T19:35:00Z',
              }),
              201,
            );
          }
          return http.Response('Not Found', 404);
        });

        final apiClient = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final syncService = SyncService(client: apiClient, prefs: prefs);
        final store = AppStore(prefs, syncService: syncService);

        // Pre-seed a draft
        await store.saveReport({
          'plantId': 'hibiscus',
          'topic': 'Plant care',
          'details': 'Pruning advice needs review for Zomba region.',
          'source': 'Local gardener',
          'createdAt': '2026-11-17T19:00:00Z',
          'status': 'local-draft',
        });

        await tester.pumpWidget(MaterialApp(home: DraftsScreen(store: store)));
        await tester.pumpAndSettle();

        expect(find.byTooltip('Submit report'), findsOneWidget);

        // Tap submit icon
        await tester.tap(find.byTooltip('Submit report'));
        await tester.pumpAndSettle();

        expect(serverReceived, isTrue);
        expect(store.reports.first['status'], 'submitted');
        expect(store.reports.first['id'], 'draft-submitted-200');
      },
    );
  });
}
