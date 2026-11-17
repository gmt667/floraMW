import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models.dart';
import 'api_client.dart';

/// Supported types of queued synchronization operations.
enum SyncOperationType { create, update, delete }

/// Represents a single durable synchronization operation in the outbox.
class SyncOperation {
  final String opId;
  final String observationId;
  final SyncOperationType type;
  final Map<String, dynamic> payload;
  final String createdAt;
  final String? identityToken;
  int attemptCount;
  String? lastAttemptAt;
  String? lastError;
  bool permanentError;

  SyncOperation({
    required this.opId,
    required this.observationId,
    required this.type,
    required this.payload,
    required this.createdAt,
    this.identityToken,
    this.attemptCount = 0,
    this.lastAttemptAt,
    this.lastError,
    this.permanentError = false,
  });

  Map<String, dynamic> toJson() => {
    'opId': opId,
    'observationId': observationId,
    'type': type.name,
    'payload': payload,
    'createdAt': createdAt,
    'identityToken': identityToken,
    'attemptCount': attemptCount,
    'lastAttemptAt': lastAttemptAt,
    'lastError': lastError,
    'permanentError': permanentError,
  };

  factory SyncOperation.fromJson(Map<String, dynamic> json) => SyncOperation(
    opId: json['opId'] as String,
    observationId: json['observationId'] as String,
    type: SyncOperationType.values.byName(json['type'] as String),
    payload: Map<String, dynamic>.from(json['payload'] as Map),
    createdAt: json['createdAt'] as String,
    identityToken: json['identityToken'] as String?,
    attemptCount: json['attemptCount'] as int? ?? 0,
    lastAttemptAt: json['lastAttemptAt'] as String?,
    lastError: json['lastError'] as String?,
    permanentError: json['permanentError'] as bool? ?? false,
  );
}

/// Result of a synchronization queue processing cycle.
class SyncProcessResult {
  final int processedCount;
  final int remainingCount;
  final bool hasNetworkError;
  final bool rateLimited;

  const SyncProcessResult({
    required this.processedCount,
    required this.remainingCount,
    required this.hasNetworkError,
    this.rateLimited = false,
  });
}

/// Result of 409 Conflict server record verification.
class ConflictVerificationResult {
  final bool isOwnerAndMatched;
  final bool needsContentUpdate;
  final String mismatchReason;

  const ConflictVerificationResult({
    required this.isOwnerAndMatched,
    this.needsContentUpdate = false,
    this.mismatchReason = '',
  });
}

/// Offline-First Synchronization Service for FloraMW Field Journal observations.
///
/// Features:
/// - Durable FIFO outbox persisted to SharedPreferences (`floramw_sync_outbox`).
/// - Deterministic operation compaction to prevent conflicting or redundant network calls.
/// - In-flight synchronization protection preventing compaction races during active transport.
/// - Startup reconciliation closing the local-state/outbox dual-write crash window.
/// - Safe 409 Conflict resolution with payload verification and content reconciliation.
/// - HTTP 429 Rate Limiting backoff respecting `Retry-After`.
/// - Anonymous identity tracking preventing orphaned queue corruption after 401.
/// - Concurrency protection serializing queue mutations and disk writes.
class SyncService {
  static const String outboxStorageKey = 'floramw_sync_outbox';
  static const String syncedStorageKey = 'floramw_synced_observations';
  static const String deletedStorageKey = 'floramw_deleted_observations';
  static const String rateLimitPauseKey = 'floramw_rate_limit_pause';
  static const String lastTokenKey = 'floramw_last_known_token';

  final FloraApiClient client;
  final SharedPreferences prefs;

  final List<SyncOperation> _queue = [];
  final Set<String> _syncedObservationIds = {};
  final Set<String> _locallyDeletedObservationIds = {};
  final Set<String> _inFlightObservationIds = {};

  bool _isProcessing = false;
  Future<SyncProcessResult>? _activeProcessingFuture;
  Future<void> _queueLock = Future.value();
  DateTime? _rateLimitPauseUntil;
  String? _lastKnownToken;

  SyncService({
    required this.client,
    required this.prefs,
  }) {
    _loadState();
  }

  /// Read-only snapshot of current outbox queue.
  List<SyncOperation> get pendingOperations => List.unmodifiable(_queue);

  /// Read-only snapshot of confirmed synchronized observation IDs.
  Set<String> get syncedObservationIds => Set.unmodifiable(_syncedObservationIds);

  /// Read-only snapshot of observations currently transmitting in flight.
  Set<String> get inFlightObservationIds => Set.unmodifiable(_inFlightObservationIds);

  /// Active rate limit pause timestamp, if currently paused.
  DateTime? get rateLimitPauseUntil => _rateLimitPauseUntil;

  /// Check whether an observation is actively in flight across the network.
  bool isInFlight(String observationId) => _inFlightObservationIds.contains(observationId);

  /// Load persisted outbox queue, synced IDs, deleted tombstones, and rate limit state.
  void _loadState() {
    try {
      final rawQueue = prefs.getString(outboxStorageKey);
      if (rawQueue != null && rawQueue.isNotEmpty) {
        final list = jsonDecode(rawQueue) as List<dynamic>;
        _queue.clear();
        for (final item in list) {
          _queue.add(SyncOperation.fromJson(Map<String, dynamic>.from(item as Map)));
        }
      }

      final rawSynced = prefs.getStringList(syncedStorageKey);
      if (rawSynced != null) {
        _syncedObservationIds.clear();
        _syncedObservationIds.addAll(rawSynced);
      }

      final rawDeleted = prefs.getStringList(deletedStorageKey);
      if (rawDeleted != null) {
        _locallyDeletedObservationIds.clear();
        _locallyDeletedObservationIds.addAll(rawDeleted);
      }

      final rawPause = prefs.getString(rateLimitPauseKey);
      if (rawPause != null && rawPause.isNotEmpty) {
        final parsed = DateTime.tryParse(rawPause);
        if (parsed != null && parsed.isAfter(DateTime.now())) {
          _rateLimitPauseUntil = parsed;
        }
      }

      _lastKnownToken = prefs.getString(lastTokenKey);
    } catch (e) {
      debugPrint('SyncService: Error restoring queue state: $e');
    }
  }

  /// Safely serialize all queue mutations and disk writes through a FIFO lock chain.
  Future<T> _synchronizedQueue<T>(Future<T> Function() action) async {
    final previousLock = _queueLock;
    final completer = Completer<void>();
    _queueLock = completer.future;
    try {
      await previousLock;
      return await action();
    } finally {
      completer.complete();
    }
  }

  /// Persist queue to SharedPreferences.
  Future<void> _saveQueue() async {
    final raw = jsonEncode(_queue.map((op) => op.toJson()).toList());
    await prefs.setString(outboxStorageKey, raw);
  }

  /// Persist synced observation IDs to SharedPreferences.
  Future<void> _saveSyncedIds() async {
    await prefs.setStringList(syncedStorageKey, _syncedObservationIds.toList());
  }

  /// Persist locally deleted observation IDs (tombstones) to SharedPreferences.
  Future<void> _saveDeletedIds() async {
    await prefs.setStringList(deletedStorageKey, _locallyDeletedObservationIds.toList());
  }

  /// Persist rate limit pause timestamp.
  Future<void> _saveRateLimitPause() async {
    if (_rateLimitPauseUntil != null && _rateLimitPauseUntil!.isAfter(DateTime.now())) {
      await prefs.setString(rateLimitPauseKey, _rateLimitPauseUntil!.toIso8601String());
    } else {
      await prefs.remove(rateLimitPauseKey);
    }
  }

  void _triggerQueueProcessing() {
    unawaited(processQueue().catchError((e) {
      return const SyncProcessResult(
        processedCount: 0,
        remainingCount: 0,
        hasNetworkError: true,
      );
    }));
  }

  /// Reconcile local discoveries against persisted outbox queue and synced IDs.
  ///
  /// Closes the dual-write crash window between [AppStore.commit] and [_saveQueue].
  /// Any observation saved in local history that was never queued and never synced
  /// is recovered into the outbox as a pending CREATE operation.
  Future<int> reconcileStartup({required List<Discovery> history}) async {
    final token = client.currentToken ?? _lastKnownToken;
    return _synchronizedQueue(() async {
      int recoveredCount = 0;
      for (final discovery in history) {
        final id = discovery.id;
        final hasQueueOp = _queue.any((op) => op.observationId == id);
        final isSynced = _syncedObservationIds.contains(id);
        final isDeleted = _locallyDeletedObservationIds.contains(id);

        if (!hasQueueOp && !isSynced && !isDeleted) {
          final payload = {
            'id': discovery.id,
            'plantId': discovery.plantId,
            'flowerId': discovery.plantId,
            'createdAt': discovery.createdAt,
            'district': discovery.district,
            'note': discovery.note,
            'isDemo': false,
          };
          final op = SyncOperation(
            opId: generateUuidV4(),
            observationId: discovery.id,
            type: SyncOperationType.create,
            payload: payload,
            createdAt: DateTime.now().toIso8601String(),
            identityToken: token,
          );
          _queue.add(op);
          recoveredCount++;
        }
      }

      if (recoveredCount > 0) {
        await _saveQueue();
        _triggerQueueProcessing();
      }
      return recoveredCount;
    });
  }

  /// Enqueue a CREATE operation when a new discovery is saved in the journal.
  Future<void> enqueueCreate(Discovery discovery, {bool isDemo = false}) async {
    final token = client.currentToken ?? _lastKnownToken;
    await _synchronizedQueue(() async {
      final payload = {
        'id': discovery.id,
        'plantId': discovery.plantId,
        'flowerId': discovery.plantId,
        'createdAt': discovery.createdAt,
        'district': discovery.district,
        'note': discovery.note,
        'isDemo': isDemo,
      };

      final op = SyncOperation(
        opId: generateUuidV4(),
        observationId: discovery.id,
        type: SyncOperationType.create,
        payload: payload,
        createdAt: DateTime.now().toIso8601String(),
        identityToken: token,
      );

      // If an operation for this observation is actively in flight, do not mutate it.
      if (_inFlightObservationIds.contains(discovery.id)) {
        _queue.add(op);
      } else {
        // Compaction: If non-in-flight op exists, replace it
        _queue.removeWhere((existing) => existing.observationId == discovery.id);
        _queue.add(op);
      }
      _locallyDeletedObservationIds.remove(discovery.id);
      await _saveDeletedIds();
      await _saveQueue();
    });

    _triggerQueueProcessing();
  }

  /// Enqueue an UPDATE operation when a journal note or district is edited.
  ///
  /// Safe against in-flight transport races: If a CREATE or UPDATE is actively
  /// transmitting over HTTP, the in-flight payload is NOT mutated. Instead, a
  /// subsequent UPDATE is appended to be sent after the in-flight request resolves.
  Future<void> enqueueUpdate(Discovery discovery) async {
    final token = client.currentToken ?? _lastKnownToken;
    await _synchronizedQueue(() async {
      final updatePayload = <String, dynamic>{
        'note': discovery.note,
        if (discovery.district != null) 'district': discovery.district,
      };

      final inFlight = _inFlightObservationIds.contains(discovery.id);

      if (inFlight) {
        // In-flight protection: Do NOT mutate in-flight payload.
        // Check if there is already a non-in-flight pending UPDATE queued after it:
        final pendingUpdateIdx = _queue.lastIndexWhere(
          (op) => op.observationId == discovery.id && op.type == SyncOperationType.update,
        );
        if (pendingUpdateIdx >= 0) {
          final updateOp = _queue[pendingUpdateIdx];
          updateOp.payload['note'] = discovery.note;
          if (discovery.district != null) {
            updateOp.payload['district'] = discovery.district;
          }
        } else {
          // Append new UPDATE to run after in-flight completes
          _queue.add(SyncOperation(
            opId: generateUuidV4(),
            observationId: discovery.id,
            type: SyncOperationType.update,
            payload: updatePayload,
            createdAt: DateTime.now().toIso8601String(),
            identityToken: token,
          ));
        }
        await _saveQueue();
        return;
      }

      // Offline Compaction Rule 1: If pending non-in-flight CREATE exists, merge payload
      final pendingCreateIdx = _queue.indexWhere(
        (op) => op.observationId == discovery.id && op.type == SyncOperationType.create,
      );
      if (pendingCreateIdx >= 0) {
        final createOp = _queue[pendingCreateIdx];
        createOp.payload['note'] = discovery.note;
        if (discovery.district != null) {
          createOp.payload['district'] = discovery.district;
        }
        await _saveQueue();
        return;
      }

      // Offline Compaction Rule 2: If pending non-in-flight UPDATE exists, merge
      final pendingUpdateIdx = _queue.indexWhere(
        (op) => op.observationId == discovery.id && op.type == SyncOperationType.update,
      );
      if (pendingUpdateIdx >= 0) {
        final updateOp = _queue[pendingUpdateIdx];
        updateOp.payload['note'] = discovery.note;
        if (discovery.district != null) {
          updateOp.payload['district'] = discovery.district;
        }
        await _saveQueue();
        return;
      }

      // Otherwise append new UPDATE
      _queue.add(SyncOperation(
        opId: generateUuidV4(),
        observationId: discovery.id,
        type: SyncOperationType.update,
        payload: updatePayload,
        createdAt: DateTime.now().toIso8601String(),
        identityToken: token,
      ));
      await _saveQueue();
    });

    _triggerQueueProcessing();
  }

  /// Enqueue a DELETE operation when an observation is deleted.
  ///
  /// Safe against in-flight transport races: If an operation is actively
  /// transmitting over HTTP, it is NOT cancelled. A subsequent DELETE is
  /// queued so the server record is deleted after the in-flight request resolves.
  Future<void> enqueueDelete(String observationId) async {
    final token = client.currentToken ?? _lastKnownToken;
    await _synchronizedQueue(() async {
      _locallyDeletedObservationIds.add(observationId);
      await _saveDeletedIds();

      final inFlight = _inFlightObservationIds.contains(observationId);

      if (inFlight) {
        // In-flight protection: An HTTP request is actively traveling.
        // Do NOT cancel the in-flight operation.
        // Remove only non-in-flight pending UPDATEs (since deletion supersedes updates)
        _queue.removeWhere(
          (op) => op.observationId == observationId &&
                  op.type == SyncOperationType.update &&
                  !_inFlightObservationIds.contains(op.observationId),
        );
        final op = SyncOperation(
          opId: generateUuidV4(),
          observationId: observationId,
          type: SyncOperationType.delete,
          payload: const {},
          createdAt: DateTime.now().toIso8601String(),
          identityToken: token,
        );
        _queue.add(op);
        _syncedObservationIds.remove(observationId);
        await _saveQueue();
        await _saveSyncedIds();
        return;
      }

      // Offline Compaction Rule 3: If non-in-flight CREATE is pending, cancel it entirely!
      final hasPendingCreate = _queue.any(
        (op) => op.observationId == observationId && op.type == SyncOperationType.create,
      );
      if (hasPendingCreate) {
        _queue.removeWhere((op) => op.observationId == observationId);
        _syncedObservationIds.remove(observationId);
        await _saveQueue();
        await _saveSyncedIds();
        return;
      }

      // Offline Compaction Rule 4: If non-in-flight UPDATE is pending, remove it in favor of DELETE
      _queue.removeWhere(
        (op) => op.observationId == observationId && op.type == SyncOperationType.update,
      );

      // Queue DELETE operation
      final op = SyncOperation(
        opId: generateUuidV4(),
        observationId: observationId,
        type: SyncOperationType.delete,
        payload: const {},
        createdAt: DateTime.now().toIso8601String(),
        identityToken: token,
      );
      _queue.add(op);
      _syncedObservationIds.remove(observationId);
      await _saveQueue();
      await _saveSyncedIds();
    });

    _triggerQueueProcessing();
  }

  /// Clear outbox queue without sending remote deletes (for local privacy wipe).
  Future<void> clearLocalOutbox() async {
    _queue.clear();
    _syncedObservationIds.clear();
    _locallyDeletedObservationIds.clear();
    _rateLimitPauseUntil = null;
    await _synchronizedQueue(() async {
      await prefs.remove(outboxStorageKey);
      await prefs.remove(syncedStorageKey);
      await prefs.remove(deletedStorageKey);
      await prefs.remove(rateLimitPauseKey);
    });
  }

  /// Process pending outbox operations in FIFO order with bounded backoff and rate-limit safety.
  Future<SyncProcessResult> processQueue() async {
    if (_activeProcessingFuture != null) {
      return await _activeProcessingFuture!;
    }

    final completer = Completer<SyncProcessResult>();
    _activeProcessingFuture = completer.future;

    try {
      final result = await _internalProcessQueue();
      completer.complete(result);
      return result;
    } catch (e, st) {
      completer.completeError(e, st);
      rethrow;
    } finally {
      _activeProcessingFuture = null;
    }
  }

  Future<SyncProcessResult> _internalProcessQueue() async {
    if (_isProcessing) {
      return SyncProcessResult(
        processedCount: 0,
        remainingCount: _queue.length,
        hasNetworkError: false,
      );
    }

    // Check rate limit pause
    if (_rateLimitPauseUntil != null) {
      if (DateTime.now().isBefore(_rateLimitPauseUntil!)) {
        return SyncProcessResult(
          processedCount: 0,
          remainingCount: _queue.length,
          hasNetworkError: true,
          rateLimited: true,
        );
      } else {
        _rateLimitPauseUntil = null;
        await _saveRateLimitPause();
      }
    }

    _isProcessing = true;
    int processedCount = 0;
    bool networkErrorEncountered = false;
    bool rateLimited = false;

    try {
      // Refresh identity token reference
      final currentToken = client.currentToken ?? await client.getDeviceToken().catchError((_) => '');
      if (currentToken.isNotEmpty) {
        if (_lastKnownToken != null && _lastKnownToken != currentToken) {
          debugPrint('SyncService: Anonymous identity refreshed.');
        }
        _lastKnownToken = currentToken;
        await prefs.setString(lastTokenKey, currentToken);
      }

      // Critical Fix 2: Mutex-protected snapshot prevents processing stale queue during concurrent mutations
      final List<SyncOperation> snapshot = await _synchronizedQueue(() async {
        return List<SyncOperation>.from(_queue);
      });

      for (final op in snapshot) {
        if (op.permanentError) continue;

        // Verify exponential backoff if previous attempts failed
        if (op.attemptCount > 0 && op.lastAttemptAt != null) {
          final lastAttempt = DateTime.tryParse(op.lastAttemptAt!);
          if (lastAttempt != null) {
            final backoffSeconds = min(300, (2 * pow(2, op.attemptCount - 1)).toInt());
            final nextAllowedAttempt = lastAttempt.add(Duration(seconds: backoffSeconds));
            if (DateTime.now().isBefore(nextAllowedAttempt)) {
              continue;
            }
          }
        }

        // High Fix 4: Identity check - If token is recorded and differs from current token, server anti-IDOR will block access
        final bool identityChanged = op.identityToken != null &&
            currentToken.isNotEmpty &&
            op.identityToken != currentToken;

        if (identityChanged && (op.type == SyncOperationType.update || op.type == SyncOperationType.delete)) {
          op.permanentError = true;
          op.lastError = 'Identity mismatch: operation belongs to prior anonymous identity. '
              'Server anti-IDOR prevents access with new identity.';
          await _synchronizedQueue(() async {
            await _saveQueue();
          });
          continue;
        }

        try {
          op.attemptCount++;
          op.lastAttemptAt = DateTime.now().toIso8601String();

          switch (op.type) {
            case SyncOperationType.create:
              await _executeCreate(op);
              break;
            case SyncOperationType.update:
              await _executeUpdate(op);
              break;
            case SyncOperationType.delete:
              await _executeDelete(op, identityChanged: identityChanged);
              break;
          }

          // Operation succeeded: remove from outbox and persist
          await _synchronizedQueue(() async {
            _queue.removeWhere((item) => item.opId == op.opId);
            await _saveQueue();
          });
          processedCount++;
        } on FloraApiException catch (e) {
          if (!op.permanentError || op.lastError == null) {
            op.lastError = e.message;
          }
          if (e.statusCode == 429) {
            // Priority 4: Rate limit handling
            rateLimited = true;
            networkErrorEncountered = true;
            final pauseSec = e.retryAfterSeconds ?? max(60, (2 * pow(2, op.attemptCount - 1)).toInt());
            _rateLimitPauseUntil = DateTime.now().add(Duration(seconds: pauseSec));
            await _synchronizedQueue(() async {
              await _saveRateLimitPause();
              await _saveQueue();
            });
            break; // Stop immediately to prevent hammering
          } else if (e.isNetworkError || (e.statusCode != null && e.statusCode! >= 500)) {
            networkErrorEncountered = true;

            await _synchronizedQueue(() async {
              if (op.type == SyncOperationType.create) {
                // Critical Fix 1: If an in-flight UPDATE was queued, merge it into CREATE payload.
                // NEVER remove a queued DELETE! Both CREATE (for retry/409 reconciliation) and
                // DELETE (to clean up the server record) must be preserved in queue order.
                final subsequentUpdateIdx = _queue.indexWhere(
                  (item) => item.observationId == op.observationId && item.type == SyncOperationType.update,
                );
                if (subsequentUpdateIdx >= 0) {
                  final updateOp = _queue[subsequentUpdateIdx];
                  op.payload['note'] = updateOp.payload['note'] ?? op.payload['note'];
                  if (updateOp.payload['district'] != null) {
                    op.payload['district'] = updateOp.payload['district'];
                  }
                  _queue.removeAt(subsequentUpdateIdx);
                }
              } else if (op.type == SyncOperationType.update) {
                final hasSubsequentDelete = _queue.any(
                  (item) => item.observationId == op.observationId && item.type == SyncOperationType.delete,
                );
                if (hasSubsequentDelete) {
                  _queue.removeWhere(
                    (item) => item.observationId == op.observationId && item.type == SyncOperationType.update,
                  );
                }
              }
              await _saveQueue();
            });
            break;
          } else if (e.statusCode == 422 || e.statusCode == 400) {
            op.permanentError = true;
            await _synchronizedQueue(() async {
              await _saveQueue();
            });
          } else {
            await _synchronizedQueue(() async {
              await _saveQueue();
            });
          }
        } catch (e) {
          op.lastError = e.toString();
          await _synchronizedQueue(() async {
            await _saveQueue();
          });
        }
      }
    } finally {
      _isProcessing = false;
    }

    return SyncProcessResult(
      processedCount: processedCount,
      remainingCount: _queue.length,
      hasNetworkError: networkErrorEncountered,
      rateLimited: rateLimited,
    );
  }

  Future<void> _executeCreate(SyncOperation op) async {
    _inFlightObservationIds.add(op.observationId);
    try {
      await client.createObservation(op.payload);
      _syncedObservationIds.add(op.observationId);
      await _saveSyncedIds();
    } on FloraApiException catch (e) {
      if (e.statusCode == 409) {
        // Priority 5: Strengthened 409 conflict verification & reconciliation
        final verification = await _verifyExistingObservation(op.observationId, op.payload);
        if (verification.isOwnerAndMatched) {
          _syncedObservationIds.add(op.observationId);
          await _saveSyncedIds();

          if (verification.needsContentUpdate) {
            final updatePayload = <String, dynamic>{
              'note': op.payload['note'] ?? '',
              if (op.payload['district'] != null) 'district': op.payload['district'],
            };
            try {
              await client.updateObservation(op.observationId, updatePayload);
            } catch (_) {
              // If inline update fails, enqueue UPDATE so it will be retried
              await _synchronizedQueue(() async {
                _queue.add(SyncOperation(
                  opId: generateUuidV4(),
                  observationId: op.observationId,
                  type: SyncOperationType.update,
                  payload: updatePayload,
                  createdAt: DateTime.now().toIso8601String(),
                  identityToken: client.currentToken ?? _lastKnownToken,
                ));
                await _saveQueue();
              });
            }
          }
          return;
        } else {
          op.permanentError = true;
          op.lastError = '409 Conflict: ${verification.mismatchReason}';
          rethrow;
        }
      }
      rethrow;
    } finally {
      _inFlightObservationIds.remove(op.observationId);
    }
  }

  Future<void> _executeUpdate(SyncOperation op) async {
    _inFlightObservationIds.add(op.observationId);
    try {
      await client.updateObservation(op.observationId, op.payload);
    } on FloraApiException catch (e) {
      if (e.statusCode == 404) {
        op.permanentError = true;
        op.lastError = '404 Not Found: Cannot update non-existent observation.';
      }
      rethrow;
    } finally {
      _inFlightObservationIds.remove(op.observationId);
    }
  }

  Future<void> _executeDelete(SyncOperation op, {bool identityChanged = false}) async {
    _inFlightObservationIds.add(op.observationId);
    try {
      await client.deleteObservation(op.observationId);
      _syncedObservationIds.remove(op.observationId);
      await _saveSyncedIds();
    } on FloraApiException catch (e) {
      if (e.statusCode == 404) {
        if (identityChanged) {
          op.permanentError = true;
          op.lastError = 'Identity mismatch on DELETE: observation not accessible under current identity (HTTP 404).';
          rethrow;
        }
        _syncedObservationIds.remove(op.observationId);
        await _saveSyncedIds();
        return;
      }
      rethrow;
    } finally {
      _inFlightObservationIds.remove(op.observationId);
    }
  }

  /// Verify 409 Conflict server record against intended client payload.
  Future<ConflictVerificationResult> _verifyExistingObservation(
    String obsId,
    Map<String, dynamic> payload,
  ) async {
    try {
      final obs = await client.getObservation(obsId);
      final expectedFlowerId = payload['flowerId'] ?? payload['plantId'] ?? payload['flower_id'];
      if (obs.flowerId != expectedFlowerId && obs.plantId != expectedFlowerId) {
        return ConflictVerificationResult(
          isOwnerAndMatched: false,
          mismatchReason: 'Flower ID mismatch: expected $expectedFlowerId, server had ${obs.flowerId}',
        );
      }

      final clientNote = payload['note'] as String? ?? '';
      final clientDistrict = payload['district'] as String?;
      final bool noteDiffers = obs.note.trim() != clientNote.trim();
      final bool districtDiffers =
          clientDistrict != null && clientDistrict.isNotEmpty && obs.district != clientDistrict;

      if (noteDiffers || districtDiffers) {
        return const ConflictVerificationResult(
          isOwnerAndMatched: true,
          needsContentUpdate: true,
        );
      }

      return const ConflictVerificationResult(
        isOwnerAndMatched: true,
        needsContentUpdate: false,
      );
    } on FloraApiException catch (e) {
      return ConflictVerificationResult(
        isOwnerAndMatched: false,
        mismatchReason: 'Observation verification failed with HTTP ${e.statusCode}: ${e.message}',
      );
    } catch (e) {
      return ConflictVerificationResult(
        isOwnerAndMatched: false,
        mismatchReason: 'Observation verification error: $e',
      );
    }
  }

  /// Directly inject a [SyncOperation] into the outbox without triggering
  /// background processing. Intended exclusively for tests.
  @visibleForTesting
  Future<void> enqueueRawForTest(SyncOperation op) async {
    await _synchronizedQueue(() async {
      _queue.removeWhere((e) => e.observationId == op.observationId);
      _queue.add(op);
      await _saveQueue();
    });
  }

  /// Inject in-flight state directly for deterministic race-condition unit tests.
  @visibleForTesting
  void setInFlightForTest(String observationId, bool inFlight) {
    if (inFlight) {
      _inFlightObservationIds.add(observationId);
    } else {
      _inFlightObservationIds.remove(observationId);
    }
  }
}
