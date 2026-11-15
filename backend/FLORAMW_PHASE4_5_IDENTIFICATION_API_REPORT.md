# FloraMW — Phase 4.5: Backend Identification API Readiness Report

**Date:** 2026-11-15  
**Repository:** `floraMW`  
**Branch:** `backend`  
**Phase:** 4.5 — Backend Identification API Readiness  

---

## 1. Executive Summary

Phase 4.5 evaluated and finalized the FloraMW backend identification API (`POST /api/v1/identifications`) to ensure full operational readiness and direct interoperability with the existing Flutter mobile application.

All inspections of the Flutter frontend (`lib/models.dart`, `lib/screens/identify.dart`, `lib/services/plant_service.dart`) were conducted strictly in **READ-ONLY** mode. Zero frontend files were modified, moved, or deleted.

The primary architectural gap identified was that the backend identification response returned structured `candidates: List[IdentificationCandidateResponse]` (with nested metadata, probabilities, and `catalogue_plant_id`), whereas the Flutter application's domain model `IdentificationResult` expects `candidateIds: List<String>` corresponding directly to catalogue plant slug IDs.

To bridge this gap cleanly without breaking any existing backend API contracts:
1. `candidate_ids: List[str]` was added to `IdentificationResponse` in `backend/app/schemas/identification.py`.
2. The identification service (`backend/app/identification/service.py`) was updated to automatically populate `candidate_ids` in order of ranking from candidates that successfully matched published catalogue plants.
3. In demo/development mode, the deterministic mock provider generates candidates matching `'hibiscus'`, `'periwinkle'`, and `'marigold'`, perfectly synchronizing with Flutter's mock and catalogue profiles.
4. Privacy, upload security (MIME validation, decompression bomb prevention, file cleanup), rate limiting, and idempotency guarantees were preserved and verified.
5. All 368 tests in the backend test suite passed with zero errors or regressions.

---

## 2. Existing Identification Architecture

The FloraMW backend identification pipeline consists of the following components:

```
[HTTP Client / Mobile App]
          │
          ▼ Multipart Form: POST /api/v1/identifications (image, [latitude], [longitude])
[Transport Security & Rate Limiting]
          │
          ▼
[Image Validation Middleware / Service]
   ├── Content-Length & Chunk Size Limits (10 MB max, 1 KB min)
   ├── Magic Bytes & MIME verification (image/jpeg, image/png, image/webp)
   ├── PIL Decompression Bomb Prevention (MAX_IMAGE_PIXELS = 25,000,000; MAX_IMAGE_DIMENSION = 8,192 px)
   └── SHA-256 Fingerprint Calculation
          │
          ▼
[Idempotency & Lease Fencing]
   ├── (fingerprint, X-Client-Request-Id, owner_user_id)
   └── Concurrency lease prevents duplicate in-flight processing
          │
          ▼
[Identification Service Pipeline]
   ├── Active Provider Execution (Deterministic Mock or External Pl@ntNet API)
   ├── Result normalization & candidate probability scoring
   ├── Catalogue Matching Service (scientific name matching against published Plant records)
   ├── Enrichment with `catalogue_plant_id` (slug), vernacular names, toxicity warnings
   └── Assembly of top-level `candidate_ids` for Flutter client consumption
          │
          ▼
[IdentificationResponse JSON (HTTP 200 / 201)]
```

### Key Technical Identifier Preservation
In accordance with system specifications, technical identifiers were strictly preserved:
- Route: `/api/v1/identifications`
- Catalogue Route: `/api/v1/plants`
- Foreign Key / Reference: `catalogue_plant_id` / `matched_plant_id`
- Model & Tables: `Plant`, `plants`, `IdentificationRequest`, `identification_requests`
- No `flower` terminology introduced into backend routes or schema identifiers.

---

## 3. Discovered Gap & Resolution

### The Gap
In Flutter `lib/models.dart`:
```dart
class IdentificationResult {
  final List<String> candidateIds;
  final bool isDemo;
  const IdentificationResult({
    required this.candidateIds,
    this.isDemo = false,
  });
}
```
And in `lib/screens/identify.dart`:
```dart
// Result processed in identify screen:
final candidatePlants = result.candidateIds
    .map((id) => plantById(id))
    .whereType<Plant>()
    .toList();
```
The Flutter client looks up plants in its local catalogue by slug ID (e.g. `'hibiscus'`, `'periwinkle'`, `'marigold'`).
Previously, the backend's `IdentificationResponse` returned candidates as an array of nested objects (`candidates: [{ "catalogue_plant_id": "hibiscus", "probability": 0.88, ... }]`), requiring clients to parse and map nested fields manually, without an explicit top-level field matching Flutter's `candidateIds` / `candidate_ids`.

### Resolution
1. Extended `IdentificationResponse` in `backend/app/schemas/identification.py` with:
   ```python
   candidate_ids: List[str] = Field(
       default_factory=list,
       description="Ordered list of catalogue plant slug IDs from matched candidates, directly compatible with Flutter IdentificationResult.candidateIds.",
   )
   ```
2. In `backend/app/identification/service.py`:
   - Updated `run_identification` for `COMPLETED` requests to extract all non-null `catalogue_plant_id` values from the enriched candidates:
     ```python
     candidate_ids = [c.catalogue_plant_id for c in enriched if c.catalogue_plant_id is not None]
     ```
   - For `NO_MATCH` requests, set `candidate_ids = []`.
   - In `_reconstruct_response_from_record`, populated `candidate_ids = [c.catalogue_plant_id for c in candidates_out if c.catalogue_plant_id is not None]`.
3. In demo mode (`provider.is_demo = True`), the provider deterministically produces candidates for *Hibiscus rosa-sinensis*, *Catharanthus roseus*, and *Tagetes erecta*, which resolve to `['hibiscus', 'periwinkle', 'marigold']`, exactly matching Flutter's catalogue slugs.

---

## 4. API Request and Response Contract

### Request
- **Endpoint:** `POST /api/v1/identifications`
- **Headers:**
  - `Content-Type: multipart/form-data`
  - `Authorization: Bearer <device_token>` *(optional for anonymous users)*
  - `X-Client-Request-Id: <uuid>` *(optional idempotency key)*
- **Form Fields:**
  - `image` *(UploadFile, required)*: Binary image (JPEG, PNG, WebP).
  - `latitude` *(float, optional)*: Geographic latitude (-90.0 to 90.0).
  - `longitude` *(float, optional)*: Geographic longitude (-180.0 to 180.0).

### Response Schema (`IdentificationResponse`)
```json
{
  "id": "c1f3a2b4-5678-4a9b-8cde-123456789abc",
  "created_at": "2026-11-15T08:00:00Z",
  "status": "COMPLETED",
  "outcome": "MATCH",
  "candidate_ids": [
    "hibiscus",
    "periwinkle",
    "marigold"
  ],
  "candidates": [
    {
      "rank": 1,
      "scientific_name": "Hibiscus rosa-sinensis",
      "common_name": "Chinese Hibiscus",
      "family": "Malvaceae",
      "probability": 0.88,
      "catalogue_plant_id": "hibiscus",
      "is_catalogue_match": true,
      "toxicity_warning": null
    },
    {
      "rank": 2,
      "scientific_name": "Catharanthus roseus",
      "common_name": "Madagascar Periwinkle",
      "family": "Apocynaceae",
      "probability": 0.72,
      "catalogue_plant_id": "periwinkle",
      "is_catalogue_match": true,
      "toxicity_warning": "toxic_if_ingested"
    },
    {
      "rank": 3,
      "scientific_name": "Tagetes erecta",
      "common_name": "African Marigold",
      "family": "Asteraceae",
      "probability": 0.65,
      "catalogue_plant_id": "marigold",
      "is_catalogue_match": true,
      "toxicity_warning": null
    }
  ],
  "provider": {
    "provider_name": "mock",
    "is_demo": true,
    "fallback_used": false
  },
  "photography_guidance": null,
  "model_version": "mock-v1",
  "execution_time_ms": 42
}
```

### Unmatched / Low-Confidence Handling
When no candidate meets the threshold (or when an image is unclassifiable):
- `status`: `"COMPLETED"`
- `outcome`: `"NO_MATCH"`
- `candidate_ids`: `[]`
- `candidates`: `[]`
- `photography_guidance`: Helpful actionable tips (e.g., "Ensure the flower or leaf is in focus, well-lit, and fills at least 50% of the frame without motion blur.").

---

## 5. Security & Privacy Verification

1. **Upload Validation:**
   - Files with invalid magic bytes (e.g. text/plain disguised as image/jpeg) return `HTTP 415 Unsupported Media Type` with code `INVALID_IMAGE_FORMAT`.
   - Files exceeding 10MB or below 1KB return `HTTP 413` or `HTTP 422`.
   - Decompression bomb images (exceeding 25 megapixels) return `HTTP 422` with code `DECOMPRESSION_BOMB_DETECTED`.
   - Temporary upload files are deleted immediately after reading/hashing, preventing disk exhaustion.
2. **Privacy Protection:**
   - Response payloads never expose user IDs, `device_token_hash`, database internal primary keys, host filesystem paths, or provider API credentials.
   - Verified via automated unit test `test_identification_response_privacy_no_user_leakage`.
3. **Idempotency & Isolation:**
   - Unauthenticated clients receive unique isolated identification IDs.
   - Same `X-Client-Request-Id` with different image fingerprints creates distinct requests without collision.

---

## 6. Test Suite Execution & Verification

### Executed Tests
1. **Identification Test Suite (`tests/test_identification.py`):**
   - 89 tests covering validation, provider execution, catalogue matching, idempotency, lease fencing, privacy, and Flutter compatibility.
   - Added:
     - `test_response_contains_candidate_ids_matching_flutter_contract`
     - `test_candidate_ids_all_retrievable_via_catalogue_api`
     - `test_missing_multipart_image_field_returns_422`
     - `test_identification_response_privacy_no_user_leakage`
   - Result: **89 passed** in 4.20s.

2. **Auth & History Test Suite (`tests/test_auth_and_history.py`):**
   - 19 tests covering anonymous registration, token hashing, device isolation, and history retrieval.
   - Result: **19 passed** in 2.39s.

3. **Complete Backend Test Suite (`pytest -v`):**
   - **Total Tests:** 368
   - **Passed:** 368 (100%)
   - **Failures:** 0
   - **Errors:** 0
   - **Duration:** 15.90s

4. **Code Quality (`ruff check`):**
   - Ran `ruff check` on modified and created backend files.
   - Result: **All checks passed! Zero warnings or lint errors.**

---

## 7. Modified Files Summary

| File | Type | Description |
|---|---|---|
| `backend/app/schemas/identification.py` | Modified | Added `candidate_ids: List[str]` field to `IdentificationResponse`. |
| `backend/app/identification/service.py` | Modified | Populated `candidate_ids` from matched candidates' `catalogue_plant_id` in `run_identification` and `_reconstruct_response_from_record`. |
| `backend/tests/test_identification.py` | Modified | Added 4 new automated tests for Flutter contract compliance, catalogue slug retrievability, privacy, and missing form fields. |
| `backend/FLORAMW_PHASE4_5_IDENTIFICATION_API_REPORT.md` | Created | Comprehensive readiness and verification report. |

*Zero frontend files (`lib/`, `pubspec.yaml`, `test/`, etc.) were modified.*

---

## 8. Remaining Limitations & Recommendations

1. **Network Connectivity vs Offline Mode:**
   - The backend identification endpoint operates over HTTP. In field conditions without internet connectivity, the Flutter mobile app will rely on its local offline plant database and offline demo service.
   - For complete remote offline ML inference, an on-device TensorFlow Lite / ONNX model would be integrated within Flutter in a future release.
2. **Catalogue Expansion:**
   - The current catalogue has four baseline verified plant profiles (`hibiscus`, `periwinkle`, `marigold`, `aloe_vera`). As more Malawian botanical profiles are curated, `catalogue_matching.py` will automatically resolve candidates to their corresponding slugs.

---

## 9. Conclusion

Phase 4.5 is **COMPLETE**. The identification API is fully tested, secure, and ready for end-to-end integration with the Flutter mobile application.

