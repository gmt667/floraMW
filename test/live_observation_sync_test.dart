import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:floramw/services/api_client.dart';
import 'package:floramw/services/sync_service.dart';
import 'package:floramw/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null; // Enable real network transport for live integration test

  test('Live FastAPI Field Journal Observation Synchronization (CRUD & 409 Resolution)', () async {
    const baseUrl = 'http://127.0.0.1:8008';

    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();

    final client = FloraApiClient(
      baseUrl: baseUrl,
      prefs: prefs,
    );

    final syncService = SyncService(
      client: client,
      prefs: prefs,
    );

    final store = AppStore(prefs, syncService: syncService);

    // 1. Authenticate & Obtain Token
    final token = await client.getDeviceToken();
    expect(token, isNotEmpty);
    expect(token.length, 64);

    // 2. CREATE Observation via AppStore (Offline-First Local Save + Queue + Live Drain)
    await store.addDiscovery('hibiscus', null);
    expect(store.history.length, 1);
    final discovery = store.history.first;
    expect(discovery.plantId, 'hibiscus');

    // Wait for queue processing to complete against live backend
    final createResult = await syncService.processQueue();
    expect(createResult.hasNetworkError, isFalse);
    expect(syncService.pendingOperations, isEmpty);
    expect(syncService.syncedObservationIds, contains(discovery.id));

    // Verify record exists on backend via direct API query
    final serverObs = await client.getObservation(discovery.id);
    expect(serverObs.id, discovery.id);
    expect(serverObs.flowerId, 'hibiscus');
    expect(serverObs.note, '');

    // 3. UPDATE Observation (Edit Note via AppStore)
    const updatedNote = 'Observed flowering near Zomba plateau in morning light.';
    await store.saveNote(discovery, updatedNote);
    expect(discovery.note, updatedNote);

    final updateResult = await syncService.processQueue();
    expect(updateResult.hasNetworkError, isFalse);
    expect(syncService.pendingOperations, isEmpty);

    // Verify server has updated note
    final updatedServerObs = await client.getObservation(discovery.id);
    expect(updatedServerObs.note, updatedNote);

    // 4. Duplicate CREATE (409 Conflict Safe Resolution)
    // Inject a raw CREATE operation directly into the outbox without triggering
    // background processing. This simulates an interrupted-network-ack scenario
    // (the CREATE was sent but the ack was lost, leaving a pending retry in the
    // queue). Using enqueueRawForTest avoids the scheduling race where
    // _triggerQueueProcessing() sets _isProcessing=true synchronously before
    // the test's explicit processQueue() call can run.
    final duplicateOp = SyncOperation(
      opId: generateUuidV4(),
      observationId: discovery.id,
      type: SyncOperationType.create,
      payload: {
        'id': discovery.id,
        'flowerId': 'hibiscus',
        'plantId': 'hibiscus',
        'note': updatedNote,
      },
      createdAt: DateTime.now().toIso8601String(),
    );
    await syncService.enqueueRawForTest(duplicateOp);
    expect(syncService.pendingOperations.length, 1);

    // Process: Should receive 409 from server, query server to verify ownership, and resolve cleanly!
    final conflictResult = await syncService.processQueue();
    expect(conflictResult.hasNetworkError, isFalse);
    expect(syncService.pendingOperations, isEmpty);
    expect(syncService.syncedObservationIds, contains(discovery.id));

    // 5. DELETE Observation via AppStore
    await store.removeDiscovery(discovery);
    expect(store.history, isEmpty);

    final deleteResult = await syncService.processQueue();
    expect(deleteResult.hasNetworkError, isFalse);
    expect(syncService.pendingOperations, isEmpty);
    expect(syncService.syncedObservationIds, isNot(contains(discovery.id)));

    // Verify server no longer returns the observation (404 Not Found)
    try {
      await client.getObservation(discovery.id);
      fail('Expected FloraApiException 404 for deleted observation');
    } on FloraApiException catch (e) {
      expect(e.statusCode, 404);
    }

    client.close();
  });
}
