import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

import '../models.dart';

/// Cryptographically secure UUIDv4 generator without external dependencies.
String generateUuidV4() {
  final random = Random.secure();
  final values = List<int>.generate(16, (i) => random.nextInt(256));
  // Set version to 0100 (UUIDv4)
  values[6] = (values[6] & 0x0f) | 0x40;
  // Set variant to 10xx (RFC 4122)
  values[8] = (values[8] & 0x3f) | 0x80;
  final hex = values.map((b) => b.toRadixString(16).padLeft(2, '0')).toList();
  return '${hex.sublist(0, 4).join()}-${hex.sublist(4, 6).join()}-${hex.sublist(6, 8).join()}-${hex.sublist(8, 10).join()}-${hex.sublist(10, 16).join()}';
}

/// Structured exception thrown for API transport, status, or validation failures.
class FloraApiException implements Exception {
  final String message;
  final int? statusCode;
  final String? errorCode;
  final bool retryable;
  final bool isNetworkError;
  final String? safetyDisclaimer;
  final int? retryAfterSeconds;

  const FloraApiException({
    required this.message,
    this.statusCode,
    this.errorCode,
    this.retryable = false,
    this.isNetworkError = false,
    this.safetyDisclaimer,
    this.retryAfterSeconds,
  });

  @override
  String toString() =>
      'FloraApiException: $message (code: $errorCode, status: $statusCode, retryAfter: $retryAfterSeconds)';
}

/// Structured candidate representation matching backend IdentificationCandidateOut schema.
class ApiIdentificationCandidate {
  final String scientificName;
  final List<String> commonNames;
  final double confidence;
  final String confidenceLevel;
  final String? family;
  final String? genus;
  final bool catalogueMatched;
  final String? flowerId;
  final String? plantId;

  const ApiIdentificationCandidate({
    required this.scientificName,
    required this.commonNames,
    required this.confidence,
    required this.confidenceLevel,
    this.family,
    this.genus,
    required this.catalogueMatched,
    this.flowerId,
    this.plantId,
  });

  factory ApiIdentificationCandidate.fromJson(Map<String, dynamic> json) {
    return ApiIdentificationCandidate(
      scientificName: json['scientific_name'] as String? ?? '',
      commonNames: (json['common_names'] as List<dynamic>? ?? [])
          .map((e) => e.toString())
          .toList(),
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
      confidenceLevel: json['confidence_level'] as String? ?? 'uncertain',
      family: json['family'] as String?,
      genus: json['genus'] as String?,
      catalogueMatched: json['catalogue_matched'] as bool? ?? false,
      flowerId:
          json['flower_id'] as String? ??
          json['catalogue_flower_id'] as String?,
      plantId:
          json['plant_id'] as String? ?? json['catalogue_plant_id'] as String?,
    );
  }
}

/// Parsed response from POST /api/v1/identifications.
class ApiIdentificationResponse {
  final String outcome;
  final List<ApiIdentificationCandidate> candidates;
  final List<String> candidateIds;
  final String? topConfidenceLevel;
  final String providerId;
  final String? modelVersion;
  final bool isDemo;
  final String safetyDisclaimer;
  final String? clientRequestId;

  const ApiIdentificationResponse({
    required this.outcome,
    required this.candidates,
    required this.candidateIds,
    this.topConfidenceLevel,
    required this.providerId,
    this.modelVersion,
    required this.isDemo,
    required this.safetyDisclaimer,
    this.clientRequestId,
  });

  factory ApiIdentificationResponse.fromJson(Map<String, dynamic> json) {
    final provider = json['provider'] as Map<String, dynamic>? ?? {};
    final candidatesList = (json['candidates'] as List<dynamic>? ?? [])
        .map(
          (c) => ApiIdentificationCandidate.fromJson(
            Map<String, dynamic>.from(c as Map),
          ),
        )
        .toList();
    final idsList = (json['candidate_ids'] as List<dynamic>? ?? [])
        .map((e) => e.toString())
        .toList();

    return ApiIdentificationResponse(
      outcome: json['outcome'] as String? ?? 'unknown',
      candidates: candidatesList,
      candidateIds: idsList,
      topConfidenceLevel: json['top_confidence_level'] as String?,
      providerId: provider['provider_id'] as String? ?? 'unknown',
      modelVersion: provider['model_version'] as String?,
      isDemo: provider['is_demo'] as bool? ?? false,
      safetyDisclaimer: json['safety_disclaimer'] as String? ?? '',
      clientRequestId: json['client_request_id'] as String?,
    );
  }
}

/// Representation of a Field Journal observation returned by the FastAPI backend.
class ApiObservation {
  final String id;
  final String flowerId;
  final String plantId;
  final String createdAt;
  final String? photoPath;
  final String? district;
  final String note;
  final bool isDemo;

  const ApiObservation({
    required this.id,
    required this.flowerId,
    required this.plantId,
    required this.createdAt,
    this.photoPath,
    this.district,
    required this.note,
    required this.isDemo,
  });

  factory ApiObservation.fromJson(Map<String, dynamic> json) => ApiObservation(
    id: json['id'] as String,
    flowerId: json['flower_id'] as String? ?? json['flowerId'] as String? ?? '',
    plantId: json['plant_id'] as String? ?? json['plantId'] as String? ?? '',
    createdAt:
        json['created_at'] as String? ?? json['createdAt'] as String? ?? '',
    photoPath: json['photo_path'] as String? ?? json['photo'] as String?,
    district: json['district'] as String?,
    note: json['note'] as String? ?? '',
    isDemo: json['is_demo'] as bool? ?? json['isDemo'] as bool? ?? false,
  );

  Map<String, dynamic> toJson() => {
    'id': id,
    'flower_id': flowerId,
    'plant_id': plantId,
    'created_at': createdAt,
    'photo_path': photoPath,
    'district': district,
    'note': note,
    'is_demo': isDemo,
  };
}

/// Lightweight FloraMW API Client.
///
/// Handles:
/// - Environment-configurable API base URL.
/// - Cryptographic anonymous device authentication bootstrap with persistence.
/// - Concurrency protection against duplicate token creation.
/// - Multipart image transmission for identification requests.
/// - Structured error parsing and timeouts.
class FloraApiClient {
  static const String tokenStorageKey = 'floramw_device_token';
  static const Duration defaultTimeout = Duration(seconds: 25);

  final http.Client _httpClient;
  final String baseUrl;
  final SharedPreferences? _prefs;

  String? _cachedToken;
  Future<String>? _tokenBootstrapFuture;

  /// Get the current cached device token, if any.
  String? get currentToken => _cachedToken;

  FloraApiClient({
    http.Client? httpClient,
    String? baseUrl,
    SharedPreferences? prefs,
  }) : _httpClient = httpClient ?? http.Client(),
       baseUrl = (baseUrl ?? defaultBaseUrl).replaceAll(RegExp(r'/+$'), ''),
       _prefs = prefs {
    if (_prefs != null) {
      _cachedToken = _prefs.getString(tokenStorageKey);
    }
  }

  /// Resolve default base URL based on runtime environment:
  /// 1. Compile-time environment override: -DFLORAMW_API_BASE_URL=...
  /// 2. Android emulator: http://10.0.2.2:8000
  /// 3. iOS/Desktop/Web: http://127.0.0.1:8000
  static String get defaultBaseUrl {
    const envUrl = String.fromEnvironment('FLORAMW_API_BASE_URL');
    if (envUrl.isNotEmpty) {
      final parsed = Uri.tryParse(envUrl);
      if (kReleaseMode &&
          (parsed == null || parsed.scheme != 'https' || parsed.host.isEmpty)) {
        throw StateError('Release API URL must be a valid HTTPS URL.');
      }
      return envUrl;
    }
    if (kReleaseMode) {
      throw StateError(
        'FLORAMW_API_BASE_URL must be set for release builds. '
        'Pass --dart-define=FLORAMW_API_BASE_URL=https://your-api-host.',
      );
    }
    if (!kIsWeb && Platform.isAndroid) {
      return 'http://10.0.2.2:8000';
    }
    return 'http://127.0.0.1:8000';
  }

  /// Bootstrap or retrieve anonymous device token.
  ///
  /// Uses a shared Future to serialize concurrent calls and avoid multiple registrations.
  Future<String> getDeviceToken({bool forceRefresh = false}) async {
    if (!forceRefresh && _cachedToken != null && _cachedToken!.isNotEmpty) {
      return _cachedToken!;
    }

    if (_prefs != null && !forceRefresh) {
      final stored = _prefs.getString(tokenStorageKey);
      if (stored != null && stored.isNotEmpty) {
        _cachedToken = stored;
        return stored;
      }
    }

    // Serialize concurrent bootstrapping
    if (_tokenBootstrapFuture != null) {
      return _tokenBootstrapFuture!;
    }

    final completer = Completer<String>();
    // Attach no-op error handler to prevent unhandled error event if no concurrent callers are attached
    completer.future.catchError((_) => '');
    _tokenBootstrapFuture = completer.future;

    try {
      final token = await _bootstrapAnonymousToken();
      _cachedToken = token;
      if (_prefs != null) {
        await _prefs.setString(tokenStorageKey, token);
      }
      completer.complete(token);
      return token;
    } catch (e) {
      completer.completeError(e);
      rethrow;
    } finally {
      _tokenBootstrapFuture = null;
    }
  }

  Future<String> _bootstrapAnonymousToken() async {
    final uri = Uri.parse('$baseUrl/api/v1/auth/anonymous');
    try {
      final response = await _httpClient
          .post(uri, headers: const {'Accept': 'application/json'})
          .timeout(const Duration(seconds: 15));

      if (response.statusCode == 201) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final token = data['device_token'] as String?;
        if (token == null || token.isEmpty) {
          throw const FloraApiException(
            message: 'Server returned empty device token.',
            statusCode: 201,
          );
        }
        return token;
      }

      final errorBody = _parseErrorBody(response.body);
      throw FloraApiException(
        message:
            errorBody['message'] ??
            'Authentication failed with status ${response.statusCode}',
        statusCode: response.statusCode,
        errorCode: errorBody['error_code'],
        retryable: errorBody['retryable'] ?? false,
      );
    } on SocketException catch (e) {
      throw FloraApiException(
        message: 'Cannot connect to FloraMW service: ${e.message}',
        isNetworkError: true,
        retryable: true,
      );
    } on TimeoutException {
      throw const FloraApiException(
        message: 'Authentication request timed out. Check your connection.',
        isNetworkError: true,
        retryable: true,
      );
    } on http.ClientException catch (e) {
      throw FloraApiException(
        message: 'Network transport failure: ${e.message}',
        isNetworkError: true,
        retryable: true,
      );
    }
  }

  /// Submit plant photograph for identification.
  ///
  /// Sends a multipart form-data request containing the image bytes.
  Future<ApiIdentificationResponse> identifyPlant({
    required String photoPath,
    String? clientRequestId,
  }) async {
    final file = File(photoPath);
    if (!await file.exists()) {
      throw FloraApiException(
        message: 'Selected photo file does not exist at path: $photoPath',
        isNetworkError: false,
      );
    }

    final reqId = clientRequestId ?? generateUuidV4();
    return _sendIdentificationRequest(
      photoPath: photoPath,
      clientRequestId: reqId,
      isRetryAfterAuth: false,
    );
  }

  Future<ApiIdentificationResponse> _sendIdentificationRequest({
    required String photoPath,
    required String clientRequestId,
    required bool isRetryAfterAuth,
  }) async {
    final token = await getDeviceToken();
    final uri = Uri.parse('$baseUrl/api/v1/identifications');

    try {
      final request = http.MultipartRequest('POST', uri);
      request.headers['Authorization'] = 'Bearer $token';
      request.headers['Accept'] = 'application/json';
      request.headers['X-Client-Request-Id'] = clientRequestId;

      final multipartFile = await http.MultipartFile.fromPath(
        'image',
        photoPath,
      );
      request.files.add(multipartFile);

      final streamedResponse = await _httpClient
          .send(request)
          .timeout(defaultTimeout);
      final response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 200) {
        final json = jsonDecode(response.body) as Map<String, dynamic>;
        return ApiIdentificationResponse.fromJson(json);
      }

      // Handle 401: Token invalid or expired. Refresh token once and retry.
      if (response.statusCode == 401 && !isRetryAfterAuth) {
        _cachedToken = null;
        if (_prefs != null) {
          await _prefs.remove(tokenStorageKey);
        }
        await getDeviceToken(forceRefresh: true);
        return await _sendIdentificationRequest(
          photoPath: photoPath,
          clientRequestId: clientRequestId,
          isRetryAfterAuth: true,
        );
      }

      final errorBody = _parseErrorBody(response.body);
      throw FloraApiException(
        message:
            errorBody['message'] ??
            'Identification failed with status ${response.statusCode}',
        statusCode: response.statusCode,
        errorCode: errorBody['error_code'],
        retryable: errorBody['retryable'] ?? false,
        safetyDisclaimer: errorBody['safety_disclaimer'],
      );
    } on SocketException catch (e) {
      throw FloraApiException(
        message: 'Unable to reach FloraMW identification service: ${e.message}',
        isNetworkError: true,
        retryable: true,
      );
    } on TimeoutException {
      throw const FloraApiException(
        message: 'Identification request timed out. Please try again.',
        isNetworkError: true,
        retryable: true,
      );
    } on http.ClientException catch (e) {
      throw FloraApiException(
        message: 'Network connection interrupted: ${e.message}',
        isNetworkError: true,
        retryable: true,
      );
    }
  }

  /// Send an authenticated JSON HTTP request with automatic 401 token refresh retry.
  Future<http.Response> _sendAuthenticatedRequest(
    String method,
    Uri uri, {
    Map<String, dynamic>? body,
    bool isRetryAfterAuth = false,
  }) async {
    http.Response response;
    try {
      final token = await getDeviceToken();
      final headers = {
        'Authorization': 'Bearer $token',
        'Accept': 'application/json',
        if (body != null) 'Content-Type': 'application/json',
      };
      switch (method.toUpperCase()) {
        case 'GET':
          response = await _httpClient
              .get(uri, headers: headers)
              .timeout(defaultTimeout);
          break;
        case 'POST':
          response = await _httpClient
              .post(
                uri,
                headers: headers,
                body: body != null ? jsonEncode(body) : null,
              )
              .timeout(defaultTimeout);
          break;
        case 'PATCH':
          response = await _httpClient
              .patch(
                uri,
                headers: headers,
                body: body != null ? jsonEncode(body) : null,
              )
              .timeout(defaultTimeout);
          break;
        case 'DELETE':
          response = await _httpClient
              .delete(uri, headers: headers)
              .timeout(defaultTimeout);
          break;
        default:
          throw UnsupportedError('Unsupported HTTP method $method');
      }

      if (response.statusCode == 401 && !isRetryAfterAuth) {
        _cachedToken = null;
        if (_prefs != null) {
          await _prefs.remove(tokenStorageKey);
        }
        await getDeviceToken(forceRefresh: true);
        return await _sendAuthenticatedRequest(
          method,
          uri,
          body: body,
          isRetryAfterAuth: true,
        );
      }

      if (response.statusCode == 429) {
        final errorBody = _parseErrorBody(response.body);
        final retryAfterHeader = response.headers['retry-after'];
        int? retryAfterSeconds;
        if (retryAfterHeader != null) {
          retryAfterSeconds = int.tryParse(retryAfterHeader);
        }
        if (retryAfterSeconds == null &&
            errorBody['retry_after_seconds'] != null) {
          retryAfterSeconds = int.tryParse(
            errorBody['retry_after_seconds'].toString(),
          );
        }
        throw FloraApiException(
          message:
              errorBody['message'] ??
              'Rate limit exceeded. Please try again later.',
          statusCode: 429,
          errorCode: errorBody['error_code'] ?? 'RATE_LIMIT_EXCEEDED',
          retryable: true,
          retryAfterSeconds: retryAfterSeconds,
        );
      }

      return response;
    } on SocketException catch (e) {
      throw FloraApiException(
        message: 'Cannot connect to FloraMW service: ${e.message}',
        isNetworkError: true,
        retryable: true,
      );
    } on TimeoutException {
      throw const FloraApiException(
        message: 'Request timed out. Please try again.',
        isNetworkError: true,
        retryable: true,
      );
    } on http.ClientException catch (e) {
      throw FloraApiException(
        message: 'Network transport failure: ${e.message}',
        isNetworkError: true,
        retryable: true,
      );
    }
  }

  /// Create a new field journal observation on the backend.
  Future<ApiObservation> createObservation(Map<String, dynamic> data) async {
    final uri = Uri.parse('$baseUrl/api/v1/flowers/observations');
    final response = await _sendAuthenticatedRequest('POST', uri, body: data);
    if (response.statusCode == 201) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return ApiObservation.fromJson(json);
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to create observation (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  /// Retrieve a specific field observation by identifier.
  Future<ApiObservation> getObservation(String obsId) async {
    final uri = Uri.parse(
      '$baseUrl/api/v1/flowers/observations/${obsId.trim()}',
    );
    final response = await _sendAuthenticatedRequest('GET', uri);
    if (response.statusCode == 200) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return ApiObservation.fromJson(json);
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to get observation (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  /// List field journal observations recorded by this user/device.
  Future<List<ApiObservation>> listObservations({
    int page = 1,
    int limit = 20,
  }) async {
    final uri = Uri.parse(
      '$baseUrl/api/v1/flowers/observations?page=$page&limit=$limit',
    );
    final response = await _sendAuthenticatedRequest('GET', uri);
    if (response.statusCode == 200) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      final items = (json['items'] as List<dynamic>? ?? [])
          .map(
            (e) => ApiObservation.fromJson(Map<String, dynamic>.from(e as Map)),
          )
          .toList();
      return items;
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to list observations (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  /// Update notes or district for a recorded observation.
  Future<ApiObservation> updateObservation(
    String obsId,
    Map<String, dynamic> data,
  ) async {
    final uri = Uri.parse(
      '$baseUrl/api/v1/flowers/observations/${obsId.trim()}',
    );
    final response = await _sendAuthenticatedRequest('PATCH', uri, body: data);
    if (response.statusCode == 200) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return ApiObservation.fromJson(json);
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to update observation (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  /// Delete a recorded observation by identifier.
  Future<void> deleteObservation(String obsId) async {
    final uri = Uri.parse(
      '$baseUrl/api/v1/flowers/observations/${obsId.trim()}',
    );
    final response = await _sendAuthenticatedRequest('DELETE', uri);
    if (response.statusCode == 204) {
      return;
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to delete observation (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  /// Retrieve flowers from the canonical botanical reference catalogue.
  Future<List<Plant>> getFlowers({
    String? search,
    String? category,
    String? family,
    String? district,
    String? sortBy,
    int page = 1,
    int limit = 50,
  }) async {
    final queryParams = <String, String>{
      'page': page.toString(),
      'limit': limit.toString(),
      if (sortBy != null && sortBy.isNotEmpty) 'sort': sortBy,
      if (search != null && search.trim().isNotEmpty) 'q': search.trim(),
      if (category != null &&
          category.trim().isNotEmpty &&
          category.trim() != 'All plants')
        'category': category.trim(),
      if (family != null && family.trim().isNotEmpty) 'family': family.trim(),
      if (district != null && district.trim().isNotEmpty)
        'district': district.trim(),
    };
    final uri = Uri.parse(
      '$baseUrl/api/v1/flowers',
    ).replace(queryParameters: queryParams);
    final response = await _sendAuthenticatedRequest('GET', uri);
    if (response.statusCode == 200) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      final items = (json['items'] as List<dynamic>? ?? []);
      return items.map((raw) {
        final m = Map<String, dynamic>.from(raw as Map);
        final id = (m['id'] ?? m['flower_id'] ?? m['plant_id'] ?? '')
            .toString();
        // Look up local plant to preserve sections and sources for ProfileScreen
        Plant? local;
        try {
          local = plants.firstWhere((p) => p.id == id);
        } catch (_) {}

        return Plant(
          id: id,
          name: (m['name'] ?? local?.name ?? '').toString(),
          scientific: (m['scientific'] ?? local?.scientific ?? '').toString(),
          family: (m['family'] ?? local?.family ?? '').toString(),
          category: (m['category'] ?? local?.category ?? 'Garden flowers')
              .toString(),
          symbol: (m['symbol'] ?? local?.symbol ?? '🌸').toString(),
          description: (m['description'] ?? local?.description ?? '')
              .toString(),
          sections: local?.sections ?? pending,
          sources: local?.sources ?? const [pmraSource],
        );
      }).toList();
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to retrieve flower catalogue (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  /// Retrieve the complete server-managed flower profile.
  Future<Plant> getFlower(String flowerId) async {
    final cleanId = flowerId.trim();
    if (cleanId.isEmpty || cleanId.contains('/')) {
      throw const FloraApiException(message: 'A valid flower ID is required.');
    }
    final uri = Uri.parse('$baseUrl/api/v1/flowers/$cleanId');
    final response = await _sendAuthenticatedRequest('GET', uri);
    if (response.statusCode != 200) {
      final errorBody = _parseErrorBody(response.body);
      throw FloraApiException(
        message: errorBody['message'] ?? 'Failed to retrieve flower profile (${response.statusCode})',
        statusCode: response.statusCode,
        errorCode: errorBody['error_code'],
        retryable: response.statusCode >= 500,
      );
    }
    final json = Map<String, dynamic>.from(jsonDecode(response.body) as Map);
    final local = plants.where((p) => p.id == cleanId).firstOrNull;
    final rawSources = json['sources'] as List<dynamic>? ?? const [];
    final sources = rawSources.map((raw) {
      final item = Map<String, dynamic>.from(raw as Map);
      return PlantSource(
        (item['title'] ?? 'Botanical reference').toString(),
        (item['url'] ?? '').toString(),
      );
    }).where((source) => source.url.isNotEmpty).toList();
    return Plant(
      id: cleanId,
      name: (json['name'] ?? local?.name ?? cleanId).toString(),
      scientific: (json['scientific'] ?? local?.scientific ?? '').toString(),
      family: (json['family'] ?? local?.family ?? '').toString(),
      category: (json['category'] ?? local?.category ?? 'Garden flowers').toString(),
      symbol: (json['symbol'] ?? local?.symbol ?? '🌸').toString(),
      description: (json['description'] ?? local?.description ?? '').toString(),
      sections: Map<String, String>.from(json['sections'] as Map? ?? local?.sections ?? pending),
      sources: sources.isNotEmpty ? sources : (local?.sources ?? const [pmraSource]),
    );
  }

  /// Submit a botanical feedback or correction report to the backend.
  Future<Map<String, dynamic>> submitReport({
    String? id,
    String? flowerId,
    String? plantId,
    required String topic,
    required String details,
    String? source,
    String? sourceReference,
  }) async {
    final cleanTopic = topic.trim();
    final cleanDetails = details.trim();
    if (cleanTopic.length < 2) {
      throw const FloraApiException(
        message: 'Report topic must be at least 2 characters long.',
        statusCode: 400,
      );
    }
    if (cleanDetails.length < 5) {
      throw const FloraApiException(
        message: 'Report details must be at least 5 characters long.',
        statusCode: 400,
      );
    }

    final targetFlower = (flowerId ?? plantId)?.trim();
    final uri = Uri.parse('$baseUrl/api/v1/flowers/reports');
    final payload = <String, dynamic>{
      if (id != null && id.trim().isNotEmpty) 'id': id.trim(),
      if (targetFlower != null && targetFlower.isNotEmpty) ...{
        'flower_id': targetFlower,
        'plant_id': targetFlower,
      },
      'topic': cleanTopic,
      'details': cleanDetails,
      if (source != null && source.trim().isNotEmpty) ...{
        'source': source.trim(),
        'source_reference': source.trim(),
      } else if (sourceReference != null &&
          sourceReference.trim().isNotEmpty) ...{
        'source': sourceReference.trim(),
        'source_reference': sourceReference.trim(),
      },
      'status': 'submitted',
    };

    final response = await _sendAuthenticatedRequest(
      'POST',
      uri,
      body: payload,
    );
    if (response.statusCode == 201) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return json;
    }
    if (response.statusCode == 409) {
      final json = jsonDecode(response.body) as Map<String, dynamic>;
      return json;
    }
    final errorBody = _parseErrorBody(response.body);
    throw FloraApiException(
      message:
          errorBody['message'] ??
          'Failed to submit report (${response.statusCode})',
      statusCode: response.statusCode,
      errorCode: errorBody['error_code'],
      retryable: response.statusCode >= 500,
    );
  }

  Map<String, dynamic> _parseErrorBody(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is Map<String, dynamic>) {
        if (decoded.containsKey('detail') && decoded['detail'] is Map) {
          return Map<String, dynamic>.from(decoded['detail'] as Map);
        }
        return decoded;
      }
    } catch (_) {}
    return <String, dynamic>{};
  }

  /// Close client resources.
  void close() {
    _httpClient.close();
  }
}

/// Adapter implementing the frontend [IdentificationService] seam to bridge
/// [IdentifyScreen] to the FastAPI [FloraApiClient].
///
/// Preserves the exact interface, demo behaviour, and offline safety.
class ApiIdentificationService implements IdentificationService {
  final FloraApiClient client;
  final IdentificationService fallback;

  ApiIdentificationService({
    required this.client,
    IdentificationService? fallback,
  }) : fallback = fallback ?? DemoIdentificationService();

  @override
  Future<IdentificationResult> identify(
    String? photoPath,
    DemoOutcome outcome,
  ) async {
    // If no photo was selected (e.g. "Explore demo without a photo"), delegate to demo fallback
    if (photoPath == null || photoPath.trim().isEmpty) {
      return fallback.identify(null, outcome);
    }

    // Preserve demo dropdown outcomes for user inspection / testing
    if (outcome == DemoOutcome.noMatch || outcome == DemoOutcome.error) {
      return fallback.identify(photoPath, outcome);
    }

    // Call live backend service with selected photo
    final response = await client.identifyPlant(photoPath: photoPath);

    return IdentificationResult(
      candidateIds: response.candidateIds
          .where((id) => plants.any((plant) => plant.id == id))
          .toList(),
      isDemo: response.isDemo,
      safetyDisclaimer: response.safetyDisclaimer,
      providerId: response.providerId,
    );
  }
}
