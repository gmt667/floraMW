import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import 'package:floramw/main.dart';
import 'package:floramw/services/api_client.dart';
import 'package:floramw/services/sync_service.dart';
import 'package:floramw/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null; // Enable real network transport

  const baseUrl = 'http://127.0.0.1:8008';

  group('Live FastAPI Backend Verification: Discover Catalogue', () {
    test(
      'Basic Catalogue Retrieval via FloraApiClient.getFlowers() against live backend',
      () async {
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();

        final client = FloraApiClient(baseUrl: baseUrl, prefs: prefs);

        // Verify token is established
        final token = await client.getDeviceToken();
        expect(token, isNotEmpty);
        expect(token.length, 64);

        // 1. Basic retrieval
        final flowers = await client.getFlowers(limit: 50);
        expect(flowers, isNotEmpty);
        expect(flowers.length, 4);

        final ids = flowers.map((f) => f.id).toList();
        expect(
          ids,
          containsAll(['hibiscus', 'periwinkle', 'frangipani', 'marigold']),
        );

        for (final flower in flowers) {
          expect(flower.id, isNotEmpty);
          expect(flower.name, isNotEmpty);
          expect(flower.scientific, isNotEmpty);
          expect(flower.family, isNotEmpty);
          expect(flower.category, isNotEmpty);
          expect(flower.symbol, isNotEmpty);
          expect(flower.description, isNotEmpty);
          expect(flower.photoAsset, contains('assets/plants/'));
          // Verify enriched botanical sections & sources
          expect(flower.sections, isNotEmpty);
          expect(flower.sources, isNotEmpty);
        }

        // 2. Query parameters - Search
        final searchResult = await client.getFlowers(search: 'hibiscus');
        expect(searchResult.length, 1);
        expect(searchResult.first.id, 'hibiscus');
        expect(searchResult.first.name, 'Chinese hibiscus');

        // 3. Query parameters - Sorting (name_desc)
        final sortDesc = await client.getFlowers(sortBy: 'name_desc');
        expect(sortDesc.length, 4);
        expect(sortDesc.first.name, 'Madagascar periwinkle');
        expect(sortDesc.last.name, 'African marigold');

        // 4. Query parameters - Pagination
        final page1 = await client.getFlowers(page: 1, limit: 2);
        final page2 = await client.getFlowers(page: 2, limit: 2);
        expect(page1.length, 2);
        expect(page2.length, 2);
        expect(page1.first.id, isNot(equals(page2.first.id)));

        client.close();
      },
    );

    testWidgets(
      'Live Discover Screen Widget renders real catalogue from live backend',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 3000);
        addTearDown(tester.view.resetPhysicalSize);

        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();

        final client = FloraApiClient(baseUrl: baseUrl, prefs: prefs);
        final syncService = SyncService(client: client, prefs: prefs);
        final store = AppStore(prefs, syncService: syncService);

        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: DiscoverScreen(store: store, onIdentify: () {}),
            ),
          ),
        );

        // Settle asynchronous HTTP fetch from live FastAPI server
        await tester.pumpAndSettle();

        // Scroll to view cards
        await tester.drag(find.byType(ListView), const Offset(0, -500));
        await tester.pumpAndSettle();

        expect(find.text('Chinese hibiscus'), findsOneWidget);
        expect(find.text('African marigold'), findsOneWidget);

        client.close();
      },
    );
  });

  group('Live FastAPI Backend Verification: Report Submission', () {
    test(
      'Successful submission, database persistence, idempotency, and owner deletion',
      () async {
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();

        final client = FloraApiClient(baseUrl: baseUrl, prefs: prefs);

        final token = await client.getDeviceToken();
        expect(token, isNotEmpty);

        final testReportId =
            'synth-test-${DateTime.now().microsecondsSinceEpoch}';

        // 1. Submit synthetic report
        final submitResult = await client.submitReport(
          id: testReportId,
          flowerId: 'hibiscus',
          topic: 'Verification Topic',
          details:
              'Synthetic report submitted during live verification testing.',
          source: 'Live Test Runner',
        );

        expect(submitResult['id'], testReportId);
        expect(submitResult['status'], 'submitted');
        expect(submitResult['flower_id'], 'hibiscus');
        expect(submitResult['topic'], 'Verification Topic');

        // 2. Verify via raw HTTP GET to reports list
        final listUri = Uri.parse('$baseUrl/api/v1/flowers/reports');
        final listResp = await http.get(
          listUri,
          headers: {
            'Authorization': 'Bearer $token',
            'Accept': 'application/json',
          },
        );
        expect(listResp.statusCode, 200);
        final listJson = jsonDecode(listResp.body) as Map<String, dynamic>;
        final userReports = (listJson['items'] as List<dynamic>? ?? []);
        final persistedReport = userReports.firstWhere(
          (r) => r['id'] == testReportId,
          orElse: () => null,
        );
        expect(persistedReport, isNotNull);
        expect(persistedReport['topic'], 'Verification Topic');

        // 3. Test Idempotency / 409 conflict handling
        final duplicateResult = await client.submitReport(
          id: testReportId,
          flowerId: 'hibiscus',
          topic: 'Verification Topic',
          details:
              'Synthetic report submitted during live verification testing.',
        );
        expect(
          duplicateResult['detail'] ?? duplicateResult['message'],
          contains('already exists'),
        );

        // 4. Test validation failure (details < 5 chars)
        expect(
          () => client.submitReport(
            flowerId: 'hibiscus',
            topic: 'Valid',
            details: 'bad',
          ),
          throwsA(
            isA<FloraApiException>().having(
              (e) => e.statusCode,
              'statusCode',
              400,
            ),
          ),
        );

        // 5. Test invalid flower reference (flower does not exist)
        expect(
          () => client.submitReport(
            flowerId: 'nonexistent_flower_xyz',
            topic: 'Valid Topic',
            details: 'Valid details for nonexistent flower.',
          ),
          throwsA(
            isA<FloraApiException>().having(
              (e) => e.statusCode,
              'statusCode',
              404,
            ),
          ),
        );

        // 6. Safe cleanup: delete synthetic test record using owner authorization
        final deleteUri = Uri.parse(
          '$baseUrl/api/v1/flowers/reports/$testReportId',
        );
        final deleteResp = await http.delete(
          deleteUri,
          headers: {'Authorization': 'Bearer $token'},
        );
        expect(deleteResp.statusCode, 204);

        // Verify deletion from server
        final verifyDeletedResp = await http.get(
          listUri,
          headers: {
            'Authorization': 'Bearer $token',
            'Accept': 'application/json',
          },
        );
        final updatedList =
            jsonDecode(verifyDeletedResp.body) as Map<String, dynamic>;
        final remaining = (updatedList['items'] as List<dynamic>? ?? [])
            .where((r) => r['id'] == testReportId)
            .toList();
        expect(remaining, isEmpty);

        client.close();
      },
    );
  });
}
