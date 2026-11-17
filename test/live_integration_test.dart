import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

import 'package:floramw/models.dart';
import 'package:floramw/services/api_client.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  HttpOverrides.global = null; // Enable real network transport for live integration test

  test('Live FastAPI Integration: Anonymous Auth, Image Upload & Identification', () async {
    const baseUrl = 'http://127.0.0.1:8008';

    // Verify backend is reachable
    final client = FloraApiClient(
      baseUrl: baseUrl,
    );

    // 1. Anonymous Authentication
    final token = await client.getDeviceToken();
    expect(token, isNotEmpty);
    expect(token.length, 64); // 256-bit token in hex = 64 characters

    // 2. Real Image Upload and Identification
    const imagePath = 'assets/plants/hibiscus.jpg';
    final imageFile = File(imagePath);
    expect(imageFile.existsSync(), isTrue);

    final reqId = generateUuidV4();
    final response = await client.identifyPlant(
      photoPath: imagePath,
      clientRequestId: reqId,
    );

    expect(response.outcome, anyOf('candidates', 'demo_mode'));
    expect(response.candidateIds, isNotEmpty);
    expect(response.safetyDisclaimer, isNotEmpty);
    expect(response.clientRequestId, reqId);

    // 3. Adapter Layer Verification
    final service = ApiIdentificationService(
      client: client,
      fallback: DemoIdentificationService(),
    );

    final result = await service.identify(imagePath, DemoOutcome.matches);
    expect(result.candidateIds, equals(response.candidateIds));
    expect(result.isDemo, equals(response.isDemo));

    // 4. Demo Fallback Behavior
    final demoResult = await service.identify(null, DemoOutcome.matches);
    expect(demoResult.isDemo, isTrue);
    expect(demoResult.candidateIds, isNotEmpty);

    final noMatchResult = await service.identify(imagePath, DemoOutcome.noMatch);
    expect(noMatchResult.isDemo, isTrue);
    expect(noMatchResult.candidateIds, isEmpty);

    client.close();
  });
}
