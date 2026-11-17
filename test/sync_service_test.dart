import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:floramw/models.dart';
import 'package:floramw/services/api_client.dart';
import 'package:floramw/services/sync_service.dart';
import 'package:floramw/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('SyncService Durable Outbox & Compaction', () {
    test('enqueues CREATE and persists to SharedPreferences', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-token',
      });
      final prefs = await SharedPreferences.getInstance();

      final mockClient = MockClient((request) async {
        return http.Response('{"detail":"Network down"}', 503);
      });
      final client = FloraApiClient(httpClient: mockClient, prefs: prefs);
      final syncService = SyncService(client: client, prefs: prefs);

      final discovery = Discovery(
        id: 'obs-1001',
        plantId: 'hibiscus',
        createdAt: '2026-11-16T20:00:00Z',
        district: 'Zomba',
        note: 'Initial observation note',
      );

      await syncService.enqueueCreate(discovery);

      expect(syncService.pendingOperations.length, 1);
      final op = syncService.pendingOperations.first;
      expect(op.observationId, 'obs-1001');
      expect(op.type, SyncOperationType.create);
      expect(op.payload['flowerId'], 'hibiscus');
      expect(op.payload['note'], 'Initial observation note');

      // Verify persisted in SharedPreferences
      final rawOutbox = prefs.getString(SyncService.outboxStorageKey);
      expect(rawOutbox, isNotNull);
      expect(rawOutbox, contains('obs-1001'));
    });

    test(
      'recovers pending outbox queue across service re-instantiation',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
          SyncService.outboxStorageKey: jsonEncode([
            {
              'opId': 'op-abc',
              'observationId': 'obs-2002',
              'type': 'create',
              'payload': {
                'id': 'obs-2002',
                'flowerId': 'marigold',
                'note': 'Restored',
              },
              'createdAt': '2026-11-16T20:00:00Z',
              'attemptCount': 1,
              'permanentError': false,
            },
          ]),
          SyncService.syncedStorageKey: ['obs-already-synced'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 200)),
          prefs: prefs,
        );

        final syncService = SyncService(client: client, prefs: prefs);
        expect(syncService.pendingOperations.length, 1);
        expect(syncService.pendingOperations.first.observationId, 'obs-2002');
        expect(
          syncService.syncedObservationIds,
          contains('obs-already-synced'),
        );
      },
    );

    test(
      'compaction: editing note before sync merges into pending CREATE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-3003',
          plantId: 'frangipani',
          createdAt: '2026-11-16T20:00:00Z',
          note: 'Draft note',
        );

        await syncService.enqueueCreate(discovery);
        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.payload['note'],
          'Draft note',
        );

        // User edits note before network sync occurs
        discovery.note = 'Updated note before sync';
        await syncService.enqueueUpdate(discovery);

        // Compaction: queue should still have exactly 1 op (the CREATE), with updated note!
        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.type,
          SyncOperationType.create,
        );
        expect(
          syncService.pendingOperations.first.payload['note'],
          'Updated note before sync',
        );
      },
    );

    test(
      'compaction: deleting observation before sync cancels pending CREATE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-4004',
          plantId: 'periwinkle',
          createdAt: '2026-11-16T20:00:00Z',
        );

        await syncService.enqueueCreate(discovery);
        expect(syncService.pendingOperations.length, 1);

        // User deletes discovery before sync
        await syncService.enqueueDelete('obs-4004');
        await Future<void>.delayed(const Duration(milliseconds: 50));

        // Compaction: CREATE cancelled, queue is completely empty (0 network calls needed)
        expect(syncService.pendingOperations, isEmpty);
        expect(prefs.getString(SyncService.outboxStorageKey), '[]');
      },
    );

    test(
      'compaction: multiple note edits on synced observation merge into single UPDATE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
          SyncService.syncedStorageKey: ['obs-5005'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-5005',
          plantId: 'hibiscus',
          createdAt: '2026-11-16T20:00:00Z',
          note: 'Edit 1',
        );

        await syncService.enqueueUpdate(discovery);
        expect(syncService.pendingOperations.length, 1);
        expect(syncService.pendingOperations.first.payload['note'], 'Edit 1');

        discovery.note = 'Edit 2 final';
        await syncService.enqueueUpdate(discovery);

        // Compaction: merges into single UPDATE
        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.type,
          SyncOperationType.update,
        );
        expect(
          syncService.pendingOperations.first.payload['note'],
          'Edit 2 final',
        );
      },
    );

    test(
      'compaction: deleting synced observation removes pending UPDATE and queues DELETE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
          SyncService.syncedStorageKey: ['obs-6006'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-6006',
          plantId: 'hibiscus',
          createdAt: '2026-11-16T20:00:00Z',
          note: 'Pending edit',
        );

        await syncService.enqueueUpdate(discovery);
        expect(
          syncService.pendingOperations.first.type,
          SyncOperationType.update,
        );

        await syncService.enqueueDelete('obs-6006');
        await Future<void>.delayed(const Duration(milliseconds: 50));

        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.type,
          SyncOperationType.delete,
        );
        expect(syncService.syncedObservationIds, isNot(contains('obs-6006')));
      },
    );
  });

  group('SyncService Network Processing & Error Handling', () {
    test(
      'successfully processes CREATE, UPDATE and DELETE against mock backend',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final requests = <String>[];
        final mockClient = MockClient((request) async {
          requests.add('${request.method} ${request.url.path}');
          if (request.method == 'POST' &&
              request.url.path.contains('/observations')) {
            return http.Response(
              jsonEncode({
                'id': 'obs-7007',
                'flower_id': 'hibiscus',
                'plant_id': 'hibiscus',
                'created_at': '2026-11-16T20:00:00Z',
                'district': 'Zomba',
                'note': 'Logged',
                'is_demo': false,
              }),
              201,
            );
          }
          if (request.method == 'PATCH' &&
              request.url.path.contains('obs-7007')) {
            return http.Response(
              jsonEncode({
                'id': 'obs-7007',
                'flower_id': 'hibiscus',
                'plant_id': 'hibiscus',
                'created_at': '2026-11-16T20:00:00Z',
                'note': 'Updated notes',
                'is_demo': false,
              }),
              200,
            );
          }
          if (request.method == 'DELETE' &&
              request.url.path.contains('obs-7007')) {
            return http.Response('', 204);
          }
          return http.Response('Not Found', 404);
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-7007',
          plantId: 'hibiscus',
          createdAt: '2026-11-16T20:00:00Z',
          district: 'Zomba',
        );

        // 1. CREATE
        await syncService.enqueueCreate(discovery);
        // Wait for async processing
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(syncService.pendingOperations, isEmpty);
        expect(syncService.syncedObservationIds, contains('obs-7007'));
        expect(requests, contains('POST /api/v1/flowers/observations'));

        // 2. UPDATE
        discovery.note = 'Updated notes';
        await syncService.enqueueUpdate(discovery);
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(syncService.pendingOperations, isEmpty);
        expect(
          requests,
          contains('PATCH /api/v1/flowers/observations/obs-7007'),
        );

        // 3. DELETE
        await syncService.enqueueDelete('obs-7007');
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(syncService.pendingOperations, isEmpty);
        expect(syncService.syncedObservationIds, isNot(contains('obs-7007')));
        expect(
          requests,
          contains('DELETE /api/v1/flowers/observations/obs-7007'),
        );
      },
    );

    test(
      'safe 409 resolution: confirms existing observation under same user',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          if (request.method == 'POST') {
            // Server returns 409 Conflict
            return http.Response(
              jsonEncode({
                'detail': "Observation with ID 'obs-8008' already exists.",
              }),
              409,
            );
          }
          if (request.method == 'GET' &&
              request.url.path.contains('obs-8008')) {
            // Verification check: returns 200 with matching flowerId (proven ownership)
            return http.Response(
              jsonEncode({
                'id': 'obs-8008',
                'flower_id': 'hibiscus',
                'plant_id': 'hibiscus',
                'created_at': '2026-11-16T20:00:00Z',
                'note': 'Verified',
                'is_demo': false,
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
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-8008',
          plantId: 'hibiscus',
          createdAt: '2026-11-16T20:00:00Z',
          note: 'Verified',
        );

        await syncService.enqueueCreate(discovery);
        await Future<void>.delayed(const Duration(milliseconds: 50));

        // Successfully resolved: marked synced, outbox cleared
        expect(syncService.pendingOperations, isEmpty);
        expect(syncService.syncedObservationIds, contains('obs-8008'));
      },
    );

    test(
      'handles network failure by retaining operation in queue for retry',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          throw http.ClientException('Connection refused');
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-9009',
          plantId: 'marigold',
          createdAt: '2026-11-16T20:00:00Z',
        );

        await syncService.enqueueCreate(discovery);
        await Future<void>.delayed(const Duration(milliseconds: 50));

        expect(syncService.pendingOperations.length, 1);
        final op = syncService.pendingOperations.first;
        expect(op.attemptCount, greaterThanOrEqualTo(1));
        expect(op.permanentError, isFalse);
        expect(op.lastError, contains('Connection refused'));
      },
    );
  });

  group('AppStore Integration with SyncService', () {
    test(
      'AppStore mutations trigger corresponding SyncService queue operations',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          return http.Response('{"detail":"offline"}', 503);
        });
        final client = FloraApiClient(httpClient: mockClient, prefs: prefs);
        final syncService = SyncService(client: client, prefs: prefs);

        final store = AppStore(prefs, syncService: syncService);

        // 1. addDiscovery
        await store.addDiscovery('hibiscus', null);
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(store.history.length, 1);
        final discovery = store.history.first;
        expect(syncService.pendingOperations.length, 1);
        expect(syncService.pendingOperations.first.observationId, discovery.id);
        expect(
          syncService.pendingOperations.first.type,
          SyncOperationType.create,
        );

        // 2. saveNote
        await store.saveNote(discovery, 'Field observation note');
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(discovery.note, 'Field observation note');
        // Compaction: updates CREATE payload
        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.payload['note'],
          'Field observation note',
        );

        // 3. removeDiscovery
        await store.removeDiscovery(discovery);
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(store.history, isEmpty);
        // Compaction: cancels pending CREATE
        expect(syncService.pendingOperations, isEmpty);
      },
    );

    test(
      'clearPersonalData clears local outbox without issuing remote deletes',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          return http.Response('{"detail":"offline"}', 503);
        });
        final client = FloraApiClient(httpClient: mockClient, prefs: prefs);
        final syncService = SyncService(client: client, prefs: prefs);

        final store = AppStore(prefs, syncService: syncService);
        await store.addDiscovery('marigold', null);
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(syncService.pendingOperations.length, 1);

        await store.clearPersonalData();
        await Future<void>.delayed(const Duration(milliseconds: 50));
        expect(store.history, isEmpty);
        expect(syncService.pendingOperations, isEmpty);
      },
    );
  });

  group('SyncService In-Flight Synchronization Protection', () {
    test(
      'CREATE in flight followed by UPDATE does not mutate in-flight payload and appends subsequent UPDATE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-inflight-1',
          plantId: 'hibiscus',
          createdAt: '2026-11-16T20:00:00Z',
          note: 'Original in-flight note',
        );

        // Enqueue CREATE
        await syncService.enqueueCreate(discovery);
        expect(syncService.pendingOperations.length, 1);
        final createOp = syncService.pendingOperations.first;
        expect(createOp.payload['note'], 'Original in-flight note');

        // Mark observation as actively transmitting in flight over network
        syncService.setInFlightForTest('obs-inflight-1', true);
        expect(syncService.isInFlight('obs-inflight-1'), isTrue);

        // User edits note while HTTP request is traveling
        discovery.note = 'Updated note during in-flight transport';
        await syncService.enqueueUpdate(discovery);

        // CRITICAL VERIFICATION: In-flight CREATE payload was NOT mutated!
        expect(syncService.pendingOperations.length, 2);
        expect(syncService.pendingOperations[0].type, SyncOperationType.create);
        expect(
          syncService.pendingOperations[0].payload['note'],
          'Original in-flight note',
        );

        // Subsequent UPDATE was appended to be sent after CREATE finishes!
        expect(syncService.pendingOperations[1].type, SyncOperationType.update);
        expect(
          syncService.pendingOperations[1].payload['note'],
          'Updated note during in-flight transport',
        );

        syncService.setInFlightForTest('obs-inflight-1', false);
      },
    );

    test(
      'CREATE in flight followed by DELETE does not cancel in-flight CREATE and appends subsequent DELETE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-inflight-2',
          plantId: 'baobab',
          createdAt: '2026-11-16T20:00:00Z',
        );

        await syncService.enqueueCreate(discovery);
        expect(syncService.pendingOperations.length, 1);

        // Mark in-flight
        syncService.setInFlightForTest('obs-inflight-2', true);

        // User deletes discovery while CREATE is traveling across the network
        await syncService.enqueueDelete('obs-inflight-2');

        // CRITICAL VERIFICATION: In-flight CREATE was NOT cancelled as if it never happened!
        // Subsequent DELETE was queued to run after CREATE reaches server!
        expect(syncService.pendingOperations.length, 2);
        expect(syncService.pendingOperations[0].type, SyncOperationType.create);
        expect(syncService.pendingOperations[1].type, SyncOperationType.delete);

        syncService.setInFlightForTest('obs-inflight-2', false);
      },
    );

    test(
      'UPDATE in flight followed by DELETE preserves in-flight UPDATE and appends subsequent DELETE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
          SyncService.syncedStorageKey: ['obs-inflight-3'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-inflight-3',
          plantId: 'acacia',
          createdAt: '2026-11-16T20:00:00Z',
          note: 'First edit',
        );

        await syncService.enqueueUpdate(discovery);
        expect(syncService.pendingOperations.length, 1);

        // Mark UPDATE in-flight
        syncService.setInFlightForTest('obs-inflight-3', true);

        // User deletes observation while UPDATE is in-flight
        await syncService.enqueueDelete('obs-inflight-3');

        // Both UPDATE and DELETE are preserved in order
        expect(syncService.pendingOperations.length, 2);
        expect(syncService.pendingOperations[0].type, SyncOperationType.update);
        expect(syncService.pendingOperations[1].type, SyncOperationType.delete);

        syncService.setInFlightForTest('obs-inflight-3', false);
      },
    );
  });

  group('SyncService Crash Consistency & Startup Reconciliation', () {
    test(
      'reconciles local discoveries missing from queue and synced set',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-token',
          // Outbox queue is empty (simulating process termination before _saveQueue)
          SyncService.outboxStorageKey: '[]',
          SyncService.syncedStorageKey: ['obs-synced-1'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final localHistory = [
          Discovery(
            id: 'obs-synced-1', // Already synced, should NOT be recovered
            plantId: 'hibiscus',
            createdAt: '2026-11-16T18:00:00Z',
          ),
          Discovery(
            id: 'obs-crashed-2', // In local history, missing from outbox and synced set!
            plantId: 'marigold',
            createdAt: '2026-11-16T19:00:00Z',
            note: 'Saved before crash',
          ),
        ];

        expect(syncService.pendingOperations, isEmpty);

        // Run startup reconciliation
        final recoveredCount = await syncService.reconcileStartup(
          history: localHistory,
        );
        expect(recoveredCount, 1);

        // Successfully recovered obs-crashed-2 into outbox as pending CREATE!
        expect(syncService.pendingOperations.length, 1);
        final recoveredOp = syncService.pendingOperations.first;
        expect(recoveredOp.observationId, 'obs-crashed-2');
        expect(recoveredOp.type, SyncOperationType.create);
        expect(recoveredOp.payload['note'], 'Saved before crash');

        // Running reconciliation again is idempotent (recovers 0)
        final secondRun = await syncService.reconcileStartup(
          history: localHistory,
        );
        expect(secondRun, 0);
        expect(syncService.pendingOperations.length, 1);
      },
    );

    test('does not re-enqueue locally deleted discoveries', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-token',
        SyncService.outboxStorageKey: '[]',
        SyncService.syncedStorageKey: [],
        SyncService.deletedStorageKey: ['obs-deleted-previously'],
      });
      final prefs = await SharedPreferences.getInstance();
      final client = FloraApiClient(
        httpClient: MockClient((_) async => http.Response('', 503)),
        prefs: prefs,
      );
      final syncService = SyncService(client: client, prefs: prefs);

      final historyWithDeleted = [
        Discovery(
          id: 'obs-deleted-previously',
          plantId: 'aloe',
          createdAt: '2026-11-16T17:00:00Z',
        ),
      ];

      final recovered = await syncService.reconcileStartup(
        history: historyWithDeleted,
      );
      expect(recovered, 0);
      expect(syncService.pendingOperations, isEmpty);
    });
  });

  group('SyncService HTTP 429 Rate Limiting', () {
    test('pauses queue processing and respects Retry-After header', () async {
      SharedPreferences.setMockInitialValues({
        FloraApiClient.tokenStorageKey: 'mock-token',
      });
      final prefs = await SharedPreferences.getInstance();

      int postCallCount = 0;
      final mockClient = MockClient((request) async {
        if (request.method == 'POST') {
          postCallCount++;
          // Emits HTTP 429 with Retry-After: 120 seconds
          return http.Response(
            jsonEncode({
              'detail': {
                'error_code': 'RATE_LIMIT_EXCEEDED',
                'message': 'Too many requests. Please wait 120 seconds.',
                'retry_after_seconds': 120,
              },
            }),
            429,
            headers: {'retry-after': '120'},
          );
        }
        return http.Response('', 404);
      });

      final client = FloraApiClient(
        httpClient: mockClient,
        baseUrl: 'http://127.0.0.1:8000',
        prefs: prefs,
      );
      final syncService = SyncService(client: client, prefs: prefs);

      await syncService.enqueueRawForTest(
        SyncOperation(
          opId: 'op-1',
          observationId: 'obs-rate-1',
          type: SyncOperationType.create,
          payload: {'id': 'obs-rate-1', 'flowerId': 'hibiscus'},
          createdAt: '2026-11-16T20:00:00Z',
        ),
      );
      await syncService.enqueueRawForTest(
        SyncOperation(
          opId: 'op-2',
          observationId: 'obs-rate-2',
          type: SyncOperationType.create,
          payload: {'id': 'obs-rate-2', 'flowerId': 'marigold'},
          createdAt: '2026-11-16T20:00:01Z',
        ),
      );

      expect(syncService.pendingOperations.length, 2);

      // Process queue: should hit 429 on first item and immediately break
      final result = await syncService.processQueue();

      expect(result.rateLimited, isTrue);
      expect(result.hasNetworkError, isTrue);
      expect(
        postCallCount,
        1,
      ); // Exactly 1 call fired: did NOT hammer the server with op-2!
      expect(syncService.pendingOperations.length, 2); // Both ops preserved
      expect(syncService.rateLimitPauseUntil, isNotNull);
      expect(
        syncService.rateLimitPauseUntil!.isAfter(
          DateTime.now().add(const Duration(seconds: 100)),
        ),
        isTrue,
      );

      // Immediate second call should be blocked by active rateLimitPause
      final immediateRetry = await syncService.processQueue();
      expect(immediateRetry.rateLimited, isTrue);
      expect(postCallCount, 1); // Still 1: zero network calls made!
    });
  });

  group('SyncService Strengthened 409 Conflict Safety', () {
    test(
      '409 with differing note triggers automatic server reconciliation UPDATE',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final requests = <String>[];
        final mockClient = MockClient((request) async {
          requests.add('${request.method} ${request.url.path}');
          if (request.method == 'POST') {
            // Server returns 409 Conflict (e.g. record was partially saved before dropped ACK)
            return http.Response(
              jsonEncode({
                'detail':
                    "Observation with ID 'obs-reconcile-409' already exists.",
              }),
              409,
            );
          }
          if (request.method == 'GET' &&
              request.url.path.contains('obs-reconcile-409')) {
            // Server has hibiscus, but note is EMPTY
            return http.Response(
              jsonEncode({
                'id': 'obs-reconcile-409',
                'flower_id': 'hibiscus',
                'plant_id': 'hibiscus',
                'created_at': '2026-11-16T20:00:00Z',
                'note': '',
                'district': 'Zomba',
                'is_demo': false,
              }),
              200,
            );
          }
          if (request.method == 'PATCH' &&
              request.url.path.contains('obs-reconcile-409')) {
            return http.Response(
              jsonEncode({
                'id': 'obs-reconcile-409',
                'flower_id': 'hibiscus',
                'note': 'Intended client field note',
                'district': 'Zomba',
                'is_demo': false,
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
        final syncService = SyncService(client: client, prefs: prefs);

        await syncService.enqueueRawForTest(
          SyncOperation(
            opId: 'op-409',
            observationId: 'obs-reconcile-409',
            type: SyncOperationType.create,
            payload: {
              'id': 'obs-reconcile-409',
              'flowerId': 'hibiscus',
              'district': 'Zomba',
              'note': 'Intended client field note',
            },
            createdAt: '2026-11-16T20:00:00Z',
          ),
        );

        final result = await syncService.processQueue();
        expect(result.hasNetworkError, isFalse);
        expect(syncService.pendingOperations, isEmpty);
        expect(syncService.syncedObservationIds, contains('obs-reconcile-409'));

        // Verified: POST -> 409, GET -> verified owner, PATCH -> updated differing note!
        expect(requests, contains('POST /api/v1/flowers/observations'));
        expect(
          requests,
          contains('GET /api/v1/flowers/observations/obs-reconcile-409'),
        );
        expect(
          requests,
          contains('PATCH /api/v1/flowers/observations/obs-reconcile-409'),
        );
      },
    );

    test(
      '409 with mismatched flowerId is flagged as permanent error and not acknowledged',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'mock-valid-token',
        });
        final prefs = await SharedPreferences.getInstance();

        final mockClient = MockClient((request) async {
          if (request.method == 'POST') {
            return http.Response(jsonEncode({'detail': 'Conflict'}), 409);
          }
          if (request.method == 'GET') {
            // Server returns a DIFFERENT flower for this observationId!
            return http.Response(
              jsonEncode({
                'id': 'obs-mismatch-409',
                'flower_id': 'completely-different-plant',
                'note': '',
                'is_demo': false,
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
        final syncService = SyncService(client: client, prefs: prefs);

        await syncService.enqueueRawForTest(
          SyncOperation(
            opId: 'op-mismatch',
            observationId: 'obs-mismatch-409',
            type: SyncOperationType.create,
            payload: {'id': 'obs-mismatch-409', 'flowerId': 'hibiscus'},
            createdAt: '2026-11-16T20:00:00Z',
          ),
        );

        final result = await syncService.processQueue();
        expect(result.remainingCount, 1);
        expect(syncService.pendingOperations.length, 1);
        final failedOp = syncService.pendingOperations.first;
        expect(failedOp.permanentError, isTrue);
        expect(failedOp.lastError, contains('Flower ID mismatch'));
        expect(
          syncService.syncedObservationIds,
          isNot(contains('obs-mismatch-409')),
        );
      },
    );
  });

  group('SyncService Ambiguous CREATE Outcome and Orphan Prevention', () {
    test(
      'ambiguous CREATE timeout followed by DELETE preserves operations, verifies 409 and deletes server record without orphans',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'token-ambiguous',
        });
        final prefs = await SharedPreferences.getInstance();

        final Map<String, Map<String, dynamic>> fakeServerDb = {};
        bool dropCreateResponse = true;

        final mockClient = MockClient((request) async {
          final path = request.url.path;

          if (request.method == 'POST' && path.endsWith('/observations')) {
            final body = jsonDecode(request.body) as Map<String, dynamic>;
            final id = body['id'] as String;

            if (fakeServerDb.containsKey(id)) {
              // Already created on previous attempt!
              return http.Response(
                jsonEncode({'detail': 'Observation already exists'}),
                409,
              );
            }

            // Server persists the observation!
            fakeServerDb[id] = {
              'id': id,
              'flower_id': body['flowerId'] ?? body['plantId'],
              'district': body['district'],
              'note': body['note'] ?? '',
              'is_demo': false,
              'user_id': 'user-1',
            };

            if (dropCreateResponse) {
              // Simulate socket drop / timeout on the return path
              throw const SocketException(
                'Connection timed out while waiting for server response',
              );
            }

            return http.Response(jsonEncode(fakeServerDb[id]), 201);
          }

          if (request.method == 'GET' && path.contains('/observations/')) {
            final id = path.split('/').last;
            if (fakeServerDb.containsKey(id)) {
              return http.Response(jsonEncode(fakeServerDb[id]), 200);
            }
            return http.Response('Not Found', 404);
          }

          if (request.method == 'DELETE' && path.contains('/observations/')) {
            final id = path.split('/').last;
            if (fakeServerDb.containsKey(id)) {
              fakeServerDb.remove(id);
              return http.Response('', 204);
            }
            return http.Response('Not Found', 404);
          }

          return http.Response('Not Found', 404);
        });

        final client = FloraApiClient(
          httpClient: mockClient,
          baseUrl: 'http://127.0.0.1:8000',
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        final discovery = Discovery(
          id: 'obs-ambiguous-1',
          plantId: 'hibiscus',
          createdAt: '2026-11-17T00:00:00Z',
          note: 'Observed near Shire river',
        );

        // 1. Enqueue CREATE
        await syncService.enqueueCreate(discovery);
        expect(syncService.pendingOperations.length, 1);

        // 2. Mark in-flight to simulate the HTTP transmission
        syncService.setInFlightForTest(discovery.id, true);

        // 3. User deletes the observation while the HTTP request is in-flight
        await syncService.enqueueDelete(discovery.id);
        expect(syncService.pendingOperations.length, 2);
        expect(syncService.pendingOperations[0].type, SyncOperationType.create);
        expect(syncService.pendingOperations[1].type, SyncOperationType.delete);

        // 4. Simulate the network failure during the in-flight CREATE
        final result1 = await syncService.processQueue();
        expect(result1.hasNetworkError, isTrue);
        // First attempt during processing catches the socket timeout for CREATE,
        // but CRITICALLY preserves BOTH operations in queue!
        expect(syncService.pendingOperations.length, 2);
        expect(syncService.pendingOperations[0].type, SyncOperationType.create);
        expect(syncService.pendingOperations[1].type, SyncOperationType.delete);

        // 5. Synchronization resumes: network restored, processQueue is invoked again
        dropCreateResponse =
            false; // Server has the record; subsequent network calls will succeed
        syncService.pendingOperations.first.attemptCount =
            0; // Reset backoff for immediate test retry
        final result2 = await syncService.processQueue();
        expect(result2.hasNetworkError, isFalse);

        // 6. Complete verification:
        // Both operations were drained in sequence
        expect(syncService.pendingOperations, isEmpty);
        // Remote server observation was cleanly deleted (NO ORPHAN RECORD!)
        expect(fakeServerDb.containsKey(discovery.id), isFalse);
        // Local synced set is clean
        expect(syncService.syncedObservationIds, isNot(contains(discovery.id)));
      },
    );
  });

  group('SyncService Queue Mutex, Concurrency and AppStore Coordination', () {
    test(
      'AppStore addDiscovery, saveNote, and removeDiscovery coordinate with SyncService without data loss',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'token-coord',
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('', 503)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);
        final store = AppStore(prefs, syncService: syncService);

        // addDiscovery awaits outbox enqueue
        await store.addDiscovery('hibiscus', null);
        expect(store.history.length, 1);
        final discovery = store.history.first;
        await syncService.processQueue();
        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.type,
          SyncOperationType.create,
        );

        // saveNote awaits outbox enqueue
        await store.saveNote(discovery, 'Updated note content');
        expect(discovery.note, 'Updated note content');
        await syncService.processQueue();
        expect(syncService.pendingOperations.length, 1);
        expect(
          syncService.pendingOperations.first.payload['note'],
          'Updated note content',
        );

        // removeDiscovery awaits outbox enqueue
        await store.removeDiscovery(discovery);
        expect(store.history, isEmpty);
        await syncService.processQueue();
        expect(syncService.pendingOperations, isEmpty);
      },
    );

    test(
      'Multiple concurrent processQueue calls return the same future and do not duplicate network operations',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'token-multiprocess',
        });
        final prefs = await SharedPreferences.getInstance();

        int postCallCount = 0;
        final mockClient = MockClient((request) async {
          if (request.method == 'POST') {
            postCallCount++;
            await Future<void>.delayed(const Duration(milliseconds: 50));
            return http.Response(
              jsonEncode({
                'id': 'obs-concurrent',
                'flower_id': 'hibiscus',
                'is_demo': false,
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
        final syncService = SyncService(client: client, prefs: prefs);

        await syncService.enqueueRawForTest(
          SyncOperation(
            opId: 'op-concurrent',
            observationId: 'obs-concurrent',
            type: SyncOperationType.create,
            payload: {'id': 'obs-concurrent', 'flowerId': 'hibiscus'},
            createdAt: DateTime.now().toIso8601String(),
          ),
        );

        // Trigger two processQueue calls concurrently
        final f1 = syncService.processQueue();
        final f2 = syncService.processQueue();

        final results = await Future.wait([f1, f2]);
        expect(results[0].processedCount, 1);
        expect(results[1].processedCount, 1);
        // Exactly 1 network call occurred!
        expect(postCallCount, 1);
        expect(syncService.pendingOperations, isEmpty);
      },
    );
  });

  group('SyncService Anonymous Identity Lifecycle', () {
    test(
      'Operation queued under old identity is blocked with permanentError when token changes',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'token-new-anonymous',
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('Not Found', 404)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        // Invalidate token by setting currentToken to something else
        await client.getDeviceToken();

        // Operation was created under old identity 'token-old-anonymous'
        await syncService.enqueueRawForTest(
          SyncOperation(
            opId: 'op-old-ident',
            observationId: 'obs-old-ident',
            type: SyncOperationType.update,
            payload: {'note': 'Edited note under old identity'},
            createdAt: DateTime.now().toIso8601String(),
            identityToken: 'token-old-anonymous',
          ),
        );

        final result = await syncService.processQueue();
        expect(result.remainingCount, 1);
        final op = syncService.pendingOperations.first;
        expect(op.permanentError, isTrue);
        expect(op.lastError, contains('Identity mismatch'));
      },
    );

    test(
      'DELETE under same identity on 404 is cleanly marked as already deleted on server',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'token-consistent',
          SyncService.syncedStorageKey: ['obs-already-deleted'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('Not Found', 404)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        await syncService.enqueueRawForTest(
          SyncOperation(
            opId: 'op-del',
            observationId: 'obs-already-deleted',
            type: SyncOperationType.delete,
            payload: const {},
            createdAt: DateTime.now().toIso8601String(),
            identityToken: 'token-consistent',
          ),
        );

        final result = await syncService.processQueue();
        expect(result.remainingCount, 0);
        expect(syncService.pendingOperations, isEmpty);
        expect(
          syncService.syncedObservationIds,
          isNot(contains('obs-already-deleted')),
        );
      },
    );

    test(
      'DELETE under changed identity on 404 is blocked and not treated as successful (anti-IDOR protection)',
      () async {
        SharedPreferences.setMockInitialValues({
          FloraApiClient.tokenStorageKey: 'token-user-2',
          SyncService.syncedStorageKey: ['obs-idor'],
        });
        final prefs = await SharedPreferences.getInstance();
        final client = FloraApiClient(
          httpClient: MockClient((_) async => http.Response('Not Found', 404)),
          prefs: prefs,
        );
        final syncService = SyncService(client: client, prefs: prefs);

        await syncService.enqueueRawForTest(
          SyncOperation(
            opId: 'op-del-idor',
            observationId: 'obs-idor',
            type: SyncOperationType.delete,
            payload: const {},
            createdAt: DateTime.now().toIso8601String(),
            identityToken: 'token-user-1', // belongs to different user!
          ),
        );

        final result = await syncService.processQueue();
        expect(result.remainingCount, 1);
        final op = syncService.pendingOperations.first;
        expect(op.permanentError, isTrue);
        expect(op.lastError, contains('Identity mismatch'));
      },
    );
  });
}
