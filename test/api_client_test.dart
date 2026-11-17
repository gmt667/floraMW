import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:floramw/models.dart';
import 'package:floramw/services/api_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('UUIDv4 Generator', () {
    test('produces valid RFC-4122 v4 UUID format', () {
      final uuidRegex = RegExp(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$',
      );
      for (int i = 0; i < 50; i++) {
        final id = generateUuidV4();
        expect(uuidRegex.hasMatch(id), isTrue, reason: 'Failed on $id');
      }
    });

    test('generates unique identifiers across calls', () {
      final ids = List.generate(100, (_) => generateUuidV4()).toSet();
      expect(ids.length, 100);
    });
  });

  group('Identification Schema Parsing', () {
    test('parses complete identification response with candidates', () {
      final json = {
        'outcome': 'candidates',
        'candidates': [
          {
            'scientific_name': 'Hibiscus rosa-sinensis',
            'common_names': ['Chinese hibiscus', 'Hawaiian hibiscus'],
            'confidence': 0.88,
            'confidence_level': 'high',
            'family': 'Malvaceae',
            'genus': 'Hibiscus',
            'catalogue_matched': true,
            'catalogue_flower_id': 'hibiscus',
            'catalogue_plant_id': 'hibiscus',
            'flower_id': 'hibiscus',
            'plant_id': 'hibiscus',
          },
          {
            'scientific_name': 'Catharanthus roseus',
            'common_names': ['Madagascar periwinkle'],
            'confidence': 0.12,
            'confidence_level': 'low',
            'family': 'Apocynaceae',
            'catalogue_matched': true,
            'flower_id': 'periwinkle',
            'plant_id': 'periwinkle',
          },
        ],
        'candidate_ids': ['hibiscus', 'periwinkle'],
        'top_confidence_level': 'high',
        'provider': {
          'provider_id': 'plantnet',
          'model_version': 'v2.0',
          'is_demo': false,
        },
        'safety_disclaimer': 'Always verify with a qualified botanist.',
        'client_request_id': 'test-uuid-1234',
      };

      final response = ApiIdentificationResponse.fromJson(json);

      expect(response.outcome, 'candidates');
      expect(response.candidates.length, 2);
      expect(response.candidateIds, ['hibiscus', 'periwinkle']);
      expect(response.isDemo, isFalse);
      expect(response.providerId, 'plantnet');
      expect(response.modelVersion, 'v2.0');
      expect(response.safetyDisclaimer, contains('qualified botanist'));
      expect(response.clientRequestId, 'test-uuid-1234');

      final top = response.candidates.first;
      expect(top.scientificName, 'Hibiscus rosa-sinensis');
      expect(top.confidence, 0.88);
      expect(top.confidenceLevel, 'high');
      expect(top.family, 'Malvaceae');
      expect(top.catalogueMatched, isTrue);
      expect(top.flowerId, 'hibiscus');
      expect(top.plantId, 'hibiscus');
    });

    test('parses no-match response with empty candidates', () {
      final json = {
        'outcome': 'no_match',
        'candidates': <Map<String, dynamic>>[],
        'candidate_ids': <String>[],
        'provider': {'provider_id': 'plantnet', 'is_demo': false},
        'safety_disclaimer': 'Safety notice',
      };

      final response = ApiIdentificationResponse.fromJson(json);
      expect(response.outcome, 'no_match');
      expect(response.candidates, isEmpty);
      expect(response.candidateIds, isEmpty);
      expect(response.isDemo, isFalse);
    });

    test('parses deterministic mock/demo response accurately', () {
      final json = {
        'outcome': 'demo_mode',
        'candidates': [
          {
            'scientific_name': 'Hibiscus rosa-sinensis',
            'common_names': [],
            'confidence': 0.75,
            'confidence_level': 'moderate',
            'catalogue_matched': true,
            'flower_id': 'hibiscus',
          },
        ],
        'candidate_ids': ['hibiscus'],
        'provider': {
          'provider_id': 'deterministic_mock',
          'model_version': 'v1.0.0',
          'is_demo': true,
        },
        'safety_disclaimer': 'Safety notice',
      };

      final response = ApiIdentificationResponse.fromJson(json);
      expect(response.outcome, 'demo_mode');
      expect(response.isDemo, isTrue);
      expect(response.providerId, 'deterministic_mock');
      expect(response.candidateIds, ['hibiscus']);
    });
  });

  group('Anonymous Authentication & Token Persistence', () {
    test(
      'bootstraps anonymous device token and persists to SharedPreferences',
      () async {
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();

        int callCount = 0;
        final mockClient = MockClient((request) async {
          if (request.url.path == '/api/v1/auth/anonymous' &&
              request.method == 'POST') {
            callCount++;
            return http.Response(
              jsonEncode({
                'user_id': '3fa85f64-5717-4562-b3fc-2c963f66afa6',
                'device_token':
                    'aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899',
                'token_type': 'bearer',
                'role': 'guest',
                'is_anonymous': true,
                'created_at': '2026-11-16T20:00:00Z',
              }),
              201,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.Response('Not Found', 404);
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );

        final token1 = await client.getDeviceToken();
        expect(
          token1,
          'aabbccddeeff00112233445566778899aabbccddeeff00112233445566778899',
        );
        expect(callCount, 1);
        expect(prefs.getString(FloraApiClient.tokenStorageKey), token1);

        // Subsequent call uses stored token and makes no HTTP call
        final token2 = await client.getDeviceToken();
        expect(token2, token1);
        expect(callCount, 1);
      },
    );

    test(
      'concurrent getDeviceToken calls trigger only one HTTP request',
      () async {
        SharedPreferences.setMockInitialValues({});
        final prefs = await SharedPreferences.getInstance();

        int callCount = 0;
        final mockClient = MockClient((request) async {
          callCount++;
          await Future<void>.delayed(const Duration(milliseconds: 50));
          return http.Response(
            jsonEncode({
              'user_id': '3fa85f64-5717-4562-b3fc-2c963f66afa6',
              'device_token': 'unique-token-test',
              'token_type': 'bearer',
              'role': 'guest',
              'is_anonymous': true,
              'created_at': '2026-11-16T20:00:00Z',
            }),
            201,
            headers: {'content-type': 'application/json'},
          );
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );

        final results = await Future.wait([
          client.getDeviceToken(),
          client.getDeviceToken(),
          client.getDeviceToken(),
        ]);

        expect(callCount, 1);
        expect(results[0], 'unique-token-test');
        expect(results[1], 'unique-token-test');
        expect(results[2], 'unique-token-test');
      },
    );

    test(
      'reloads existing token from SharedPreferences on initialization',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'previously-saved-token-xyz',
        });
        final prefs = await SharedPreferences.getInstance();

        int callCount = 0;
        final mockClient = MockClient((request) async {
          callCount++;
          return http.Response('Error', 500);
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );

        final token = await client.getDeviceToken();
        expect(token, 'previously-saved-token-xyz');
        expect(callCount, 0); // Zero HTTP calls made
      },
    );
  });

  group('HTTP Errors and Exception Handling', () {
    test(
      'handles 400 Bad Request with structured IdentificationErrorResponse',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'valid-test-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'detail': {
                'error_code': 'image_empty',
                'message': 'Uploaded image file contains zero bytes.',
                'retryable': false,
                'safety_disclaimer': 'Disclaimer statement.',
              },
            }),
            400,
            headers: {'content-type': 'application/json'},
          );
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );

        // Create a temporary file
        final tempDir = Directory.systemTemp.createTempSync('floramw_test_');
        final tempFile = File('${tempDir.path}/test.jpg')
          ..writeAsStringSync('dummy');

        try {
          await client.identifyPlant(photoPath: tempFile.path);
          fail('Expected FloraApiException');
        } on FloraApiException catch (e) {
          expect(e.statusCode, 400);
          expect(e.errorCode, 'image_empty');
          expect(e.message, contains('zero bytes'));
          expect(e.retryable, isFalse);
        } finally {
          tempDir.deleteSync(recursive: true);
        }
      },
    );

    test('handles 503 Provider Unavailable with retryable flag', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'valid-test-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({
            'detail': {
              'error_code': 'provider_unavailable',
              'message': 'Provider is temporarily unreachable.',
              'retryable': true,
            },
          }),
          503,
          headers: {'content-type': 'application/json'},
        );
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );

      final tempDir = Directory.systemTemp.createTempSync('floramw_test_');
      final tempFile = File('${tempDir.path}/test.jpg')
        ..writeAsStringSync('dummy');

      try {
        await client.identifyPlant(photoPath: tempFile.path);
        fail('Expected FloraApiException');
      } on FloraApiException catch (e) {
        expect(e.statusCode, 503);
        expect(e.errorCode, 'provider_unavailable');
        expect(e.retryable, isTrue);
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });

    test('re-authenticates and retries on 401 Unauthorized', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'expired-token',
      });
      final prefs = await SharedPreferences.getInstance();

      int identifyAttempts = 0;
      int authAttempts = 0;

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/auth/anonymous') {
          authAttempts++;
          return http.Response(
            jsonEncode({
              'user_id': 'new-user-id',
              'device_token': 'fresh-token-12345',
              'token_type': 'bearer',
              'role': 'guest',
              'is_anonymous': true,
              'created_at': '2026-11-16T20:00:00Z',
            }),
            201,
          );
        }

        if (request.url.path == '/api/v1/identifications') {
          identifyAttempts++;
          final auth = request.headers['authorization'] ?? '';
          if (auth.contains('expired-token')) {
            return http.Response('{"detail":"Token expired"}', 401);
          }
          if (auth.contains('fresh-token-12345')) {
            return http.Response(
              jsonEncode({
                'outcome': 'candidates',
                'candidates': [],
                'candidate_ids': ['hibiscus'],
                'provider': {'provider_id': 'mock', 'is_demo': true},
                'safety_disclaimer': 'Safe',
              }),
              200,
            );
          }
        }
        return http.Response('Not Found', 404);
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );

      final tempDir = Directory.systemTemp.createTempSync('floramw_test_');
      final tempFile = File('${tempDir.path}/test.jpg')
        ..writeAsStringSync('dummy');

      try {
        final res = await client.identifyPlant(photoPath: tempFile.path);
        expect(res.candidateIds, ['hibiscus']);
        expect(identifyAttempts, 2);
        expect(authAttempts, 1);
        expect(
          prefs.getString(FloraApiClient.tokenStorageKey),
          'fresh-token-12345',
        );
      } finally {
        tempDir.deleteSync(recursive: true);
      }
    });
  });

  group('ApiIdentificationService Adapter', () {
    test('preserves demo outcome noMatch without network request', () async {
      final mockClient = MockClient((request) async {
        fail('Should not make network request for DemoOutcome.noMatch');
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
      );
      final service = ApiIdentificationService(client: client);

      final result = await service.identify(
        'any_path.jpg',
        DemoOutcome.noMatch,
      );
      expect(result.candidateIds, isEmpty);
      expect(result.isDemo, isTrue);
    });

    test('preserves demo outcome error without network request', () async {
      final mockClient = MockClient((request) async {
        fail('Should not make network request for DemoOutcome.error');
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
      );
      final service = ApiIdentificationService(client: client);

      await expectLater(
        service.identify('any_path.jpg', DemoOutcome.error),
        throwsA(isA<Exception>()),
      );
    });

    test('delegates to fallback demo service when photoPath is null', () async {
      final mockClient = MockClient((request) async {
        fail('Should not make network request when photoPath is null');
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
      );
      final service = ApiIdentificationService(
        client: client,
        fallback: DemoIdentificationService(),
      );

      final result = await service.identify(null, DemoOutcome.matches);
      expect(result.candidateIds, ['hibiscus', 'periwinkle', 'marigold']);
      expect(result.isDemo, isTrue);
    });

    test(
      'maps live API response to IdentificationResult with genuine/demo flag',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          if (request.url.path == '/api/v1/identifications') {
            return http.Response(
              jsonEncode({
                'outcome': 'candidates',
                'candidates': [
                  {
                    'scientific_name': 'Hibiscus rosa-sinensis',
                    'common_names': [],
                    'confidence': 0.95,
                    'confidence_level': 'high',
                    'catalogue_matched': true,
                    'flower_id': 'hibiscus',
                  },
                ],
                'candidate_ids': ['hibiscus'],
                'provider': {
                  'provider_id': 'plantnet',
                  'model_version': 'v2.0',
                  'is_demo': false,
                },
                'safety_disclaimer': 'Safe',
              }),
              200,
            );
          }
          return http.Response('Not Found', 404);
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final service = ApiIdentificationService(client: client);

        final tempDir = Directory.systemTemp.createTempSync('floramw_test_');
        final tempFile = File('${tempDir.path}/hibiscus.jpg')
          ..writeAsStringSync('bytes');

        try {
          final result = await service.identify(
            tempFile.path,
            DemoOutcome.matches,
          );
          expect(result.candidateIds, ['hibiscus']);
          expect(result.isDemo, isFalse);
        } finally {
          tempDir.deleteSync(recursive: true);
        }
      },
    );
  });

  group('Catalogue Retrieval (getFlowers)', () {
    test('retrieves and parses flower catalogue successfully', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-valid-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/flowers') {
          expect(request.headers['Authorization'], 'Bearer mock-valid-token');
          expect(request.url.queryParameters['page'], '1');
          expect(request.url.queryParameters['limit'], '50');
          return http.Response(
            jsonEncode({
              'total': 2,
              'page': 1,
              'limit': 50,
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

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );

      final flowers = await client.getFlowers();
      expect(flowers.length, 2);
      expect(flowers.first.id, 'hibiscus');
      expect(flowers.first.name, 'Chinese hibiscus');
      expect(flowers.first.scientific, 'Hibiscus rosa-sinensis');
      expect(flowers.first.sections, isNotEmpty);
      expect(flowers.first.sources, isNotEmpty);
    });

    test(
      'encodes search, district, category and sorting parameters correctly',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          if (request.url.path == '/api/v1/flowers') {
            expect(request.url.queryParameters['q'], 'munda');
            expect(request.url.queryParameters['district'], 'Zomba');
            expect(request.url.queryParameters['category'], 'Garden flowers');
            expect(request.url.queryParameters['sort'], 'name_desc');
            return http.Response(
              jsonEncode({
                'total': 0,
                'page': 1,
                'limit': 20,
                'total_pages': 1,
                'has_more': false,
                'items': [],
              }),
              200,
            );
          }
          return http.Response('Not Found', 404);
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );

        final flowers = await client.getFlowers(
          search: 'munda',
          district: 'Zomba',
          category: 'Garden flowers',
          sortBy: 'name_desc',
          limit: 20,
        );
        expect(flowers, isEmpty);
      },
    );

    test('handles server error and throws FloraApiException', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-valid-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        return http.Response(
          jsonEncode({'message': 'Internal database connection failure'}),
          500,
        );
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );

      expect(
        () => client.getFlowers(),
        throwsA(
          isA<FloraApiException>()
              .having((e) => e.statusCode, 'statusCode', 500)
              .having((e) => e.retryable, 'retryable', isTrue),
        ),
      );
    });
  });

  group('Report Submission (submitReport)', () {
    test('submits report with valid payload and parses response', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-valid-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        if (request.url.path == '/api/v1/flowers/reports' &&
            request.method == 'POST') {
          expect(request.headers['Authorization'], 'Bearer mock-valid-token');
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          expect(body['flower_id'], 'hibiscus');
          expect(body['topic'], 'Identification');
          expect(body['details'], 'Flower petal shape has unusual serrations.');
          expect(body['source'], 'Field observation note');
          expect(body['status'], 'submitted');
          return http.Response(
            jsonEncode({
              'id': 'report-uuid-9999',
              'flower_id': 'hibiscus',
              'plant_id': 'hibiscus',
              'topic': 'Identification',
              'details': 'Flower petal shape has unusual serrations.',
              'source': 'Field observation note',
              'status': 'submitted',
              'created_at': '2026-11-17T19:30:00Z',
              'createdAt': '2026-11-17T19:30:00Z',
            }),
            201,
          );
        }
        return http.Response('Not Found', 404);
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );

      final result = await client.submitReport(
        flowerId: 'hibiscus',
        topic: 'Identification',
        details: 'Flower petal shape has unusual serrations.',
        source: 'Field observation note',
      );
      expect(result['id'], 'report-uuid-9999');
      expect(result['status'], 'submitted');
    });

    test('validates minimum field lengths before sending request', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-valid-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final client = FloraApiClient(
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );

      // Topic too short (<2 chars)
      expect(
        () => client.submitReport(
          topic: 'A',
          details: 'Valid details over 5 chars',
        ),
        throwsA(
          isA<FloraApiException>().having(
            (e) => e.statusCode,
            'statusCode',
            400,
          ),
        ),
      );

      // Details too short (<5 chars)
      expect(
        () => client.submitReport(topic: 'Valid topic', details: 'Bad'),
        throwsA(
          isA<FloraApiException>().having(
            (e) => e.statusCode,
            'statusCode',
            400,
          ),
        ),
      );
    });

    test(
      'handles 409 conflict gracefully for idempotent duplicate submissions',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          return http.Response(
            jsonEncode({
              'id': 'report-uuid-existing',
              'status': 'submitted',
              'message': 'Report with this ID already exists',
            }),
            409,
          );
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );

        final result = await client.submitReport(
          id: 'report-uuid-existing',
          topic: 'Plant care',
          details: 'Duplicate submission test',
        );
        expect(result['id'], 'report-uuid-existing');
      },
    );
  });
}
