# FloraMW — Phase 5: Flutter–Backend Integration Report

**Date:** 2026-11-15  
**Repository:** `floraMW`  
**Branch:** `backend`  
**Phase:** 5 — Backend-only integration compatibility audit  

---

## 1. Executive Summary

This phase inspected all Flutter source files and verified every backend API contract against them.

**The backend is fully compatible with the data models, field names, and response structures the Flutter application expects.**

However, a **fundamental structural blocker** was identified: the Flutter application contains **no networking code** of any kind. It makes no HTTP requests, holds no HTTP client, implements no token storage, and has no API service layer. The integration gap cannot be resolved from the backend side alone.

**Backend files modified in Phase 5:** None. The backend is already compatible.  
**Flutter files modified:** None — strictly read-only throughout.  
**Tests run:** 368 backend tests, all passed.

---

## 2. Flutter Contracts Inspected

The following Flutter source files were read in full (read-only):

| File | Purpose |
|---|---|
| `lib/models.dart` | `Plant`, `PlantSource`, `Discovery`, `IdentificationResult`, `IdentificationService`, `DemoIdentificationService` |
| `lib/main.dart` | App bootstrap, `HomeScreen`, `DiscoverScreen`, `WelcomeScreen`, service wiring |
| `lib/store.dart` | `AppStore` — local state, `SharedPreferences` persistence, `Discovery` history |
| `lib/preferences.dart` | `DistrictSelector`, `DistrictPicker`, `SetupScreen` — all local |
| `lib/locale_data.dart` | `districtsByRegion`, `allDistricts` — static local data |
| `lib/screens/identify.dart` | `IdentifyScreen` — identification UI, `IdentificationService` usage |
| `lib/screens/garden.dart` | `GardenScreen`, `JournalScreen` — local discovery history |
| `lib/screens/profile.dart` | `ProfileScreen`, `ReportScreen`, `PhotoCredits` — local plant profile |
| `lib/screens/settings.dart` | `SettingsScreen`, `DraftsScreen` — local settings |
| `lib/screens/translations.dart` | Translation review — local only |
| `lib/ui.dart` | Shared UI widgets — no networking |
| `pubspec.yaml` | Dependencies list |

---

## 3. The Fundamental Structural Blocker

### Finding: The Flutter application has no networking implementation

A systematic search of all Dart files in `lib/` confirmed:

- **No HTTP client** — `package:http`, `package:dio`, or any other HTTP library is **not imported in any Dart file**.
- **No `http` dependency** in `pubspec.yaml` — only `image_picker`, `path_provider`, `shared_preferences`, `url_launcher` are listed.
- **No `IdentificationService` backend implementation** — the only concrete implementation is `DemoIdentificationService` in `lib/models.dart`, which simulates results locally with a fixed 1.2-second delay.
- **No authentication code** — no token request, no token storage, no `Authorization: Bearer` header construction anywhere.
- **No base URL configuration** — no backend URL is referenced anywhere in Dart code.
- **No API service layer** — no `services/` directory, no `api_client.dart`, no `plant_service.dart`, no networking helper of any kind.
- **`DemoIdentificationService` is hardcoded** in `main.dart` line 354: `IdentifyScreen(store: s, service: DemoIdentificationService())`.

This is not an API contract mismatch. The Flutter frontend is a self-contained, fully offline demonstration application. Backend connectivity has not yet been implemented on the Flutter side.

### What this means

No backend change can establish connectivity with an application that makes no HTTP requests. The integration requires the Flutter team to add:

1. An HTTP client package (`package:http` or equivalent).
2. A `BackendIdentificationService` that implements the existing `IdentificationService` interface.
3. Anonymous authentication logic (call `POST /api/v1/auth/anonymous`, store token).
4. `Authorization: Bearer <token>` header attachment on protected requests.
5. A wiring change in `main.dart` to inject `BackendIdentificationService` instead of `DemoIdentificationService`.

None of these require any structural changes to the Flutter UI, models, or existing service interface — only additions to the service layer and one wiring change.

---

## 4. API Contract Compatibility Verification

Despite the structural blocker above, every backend contract was verified against the Flutter data models. All pass.

### 4.1 Plant Catalogue (`GET /api/v1/plants`, `GET /api/v1/plants/{id}`)

Flutter `Plant` model fields (`lib/models.dart` lines 6–22):

| Flutter field | Backend field (`PlantSummaryOut`) | Match |
|---|---|---|
| `id` | `id` | ✅ |
| `name` | `name` (mapped from `common_name_en`) | ✅ |
| `scientific` | `scientific` (mapped from `scientific_name`) | ✅ |
| `family` | `family` | ✅ |
| `category` | `category` | ✅ |
| `symbol` | `symbol` | ✅ |
| `description` | `description` | ✅ |
| `sections: Map<String, String>` | `sections: Dict[str, str]` | ✅ |
| `sources: List<PlantSource>` | `sources: List[PlantSourceOut]` | ✅ |

Flutter `PlantSource` constructor: `PlantSource(this.title, this.url)`.  
Backend `PlantSourceOut` fields: `title: str`, `url: str`. ✅

`plant.photoAsset` resolves to `"assets/plants/$id.jpg"` in Flutter.  
Backend `photo_asset` returns `"assets/plants/{id}.jpg"`. ✅

**Plant slugs present in backend catalogue:**

| Slug | Flutter ID | Match |
|---|---|---|
| `hibiscus` | `hibiscus` | ✅ |
| `periwinkle` | `periwinkle` | ✅ |
| `marigold` | `marigold` | ✅ |
| `frangipani` | `frangipani` | ✅ |

All 4 Flutter `Plant` records are seeded in the backend database and returned by `GET /api/v1/plants`. ✅

### 4.2 Plant Identification (`POST /api/v1/identifications`)

Flutter `IdentificationResult` (`lib/models.dart` lines 223–230):

```dart
class IdentificationResult {
  final List<String> candidateIds;
  final bool isDemo;
}
```

Backend `IdentificationResponse` fields:

| Flutter field | Backend field | Match |
|---|---|---|
| `candidateIds: List<String>` | `candidate_ids: List[str]` | ✅ |
| `isDemo: bool` | `provider.is_demo: bool` | ✅ (nested under `provider`) |

> [!NOTE]
> `isDemo` is nested at `response.provider.is_demo` in the backend JSON. When Flutter implements a `BackendIdentificationService`, it will need to extract `provider.is_demo` from the response body and map it to `IdentificationResult.isDemo`. This is a known and documented field — no backend change is needed.

Demo mode candidate IDs match Flutter's `DemoIdentificationService`:

| Backend demo `candidate_ids` | Flutter demo `candidateIds` |
|---|---|
| `["hibiscus", "periwinkle", "marigold"]` | `["hibiscus", "periwinkle", "marigold"]` |

✅ Exact match.

Flutter's `identify.dart` line 88 calls `widget.service.identify(path, outcome)`. The `IdentificationService` interface accepts `String? photoPath` — the backend expects `multipart/form-data` with field name `image`. This is straightforward to map in a `BackendIdentificationService` implementation.

### 4.3 Anonymous Authentication (`POST /api/v1/auth/anonymous`)

The backend returns:

```json
{
  "user_id": "uuid",
  "device_token": "64-hex-char-token",
  "token_type": "bearer",
  "role": "guest",
  "is_anonymous": true,
  "created_at": "2026-11-15T10:00:00Z"
}
```

The `device_token` is what Flutter would store in `SharedPreferences` and attach as `Authorization: Bearer <token>`. The backend validates it correctly via SHA-256 hash lookup. ✅

### 4.4 Identification History (`GET /api/v1/identifications`)

Flutter's local `Discovery` model (`lib/store.dart` lines 191–218) uses:
- `id`, `plantId`, `createdAt`, `photo`, `district`, `note`

The backend `IdentificationHistoryItemOut` schema uses:
- `id`, `outcome`, `created_at`, `candidate_count`, `provider_id`

These are **parallel** (not identical) models. The backend history records identification events; the Flutter `Discovery` records user journal entries. They serve different purposes and are not expected to map 1:1. A `BackendIdentificationService` would use `candidate_ids` from identification responses to populate local `Discovery` records — which is precisely how `store.addDiscovery(plantId, path)` is called in `identify.dart` line 257. ✅ No schema conflict.

### 4.5 Malawi Districts (`GET /api/v1/districts`)

Backend district names seeded from `lib/locale_data.dart` via `seed.py`:

| Region | Flutter `districtsByRegion` count | Backend seeded count | Match |
|---|---|---|---|
| Northern | 6 | 6 | ✅ |
| Central | 9 | 9 | ✅ |
| Southern | 13 | 13 | ✅ |
| **Total** | **28** | **28** | ✅ |

All 28 district names are identical between `locale_data.dart` and `seed.py`. The Flutter app currently uses local district data exclusively — no backend call is made. The backend district API is compatible for future use. ✅

### 4.6 HTTP Status Codes and Error Structure

Flutter's `identify.dart` only catches a generic `Exception` from `widget.service.identify(...)` and shows a fixed error string to the user (line 90–94). It does not parse structured error codes. The backend's structured `IdentificationErrorResponse` is well-suited for a `BackendIdentificationService` to interpret — the Flutter service implementation can map error codes to user-readable messages without any Flutter UI changes. ✅

---

## 5. Backend Endpoints Checked

| Endpoint | Contract verified | Status |
|---|---|---|
| `GET /` | Returns `service`, `version`, `environment`, `api_v1`, `docs` | ✅ Ready |
| `GET /health` | Returns `status`, `database`, `version`, `environment` | ✅ Ready |
| `POST /api/v1/auth/anonymous` | Returns `user_id`, `device_token`, `token_type`, `role`, `is_anonymous`, `created_at` | ✅ Ready |
| `POST /api/v1/identifications` | Returns `candidate_ids`, `provider.is_demo`, `candidates`, `outcome`, `safety_disclaimer` | ✅ Ready |
| `GET /api/v1/identifications` | Paginated history, authenticated, anti-IDOR | ✅ Ready |
| `GET /api/v1/identifications/{id}` | Full detail + candidates, authenticated | ✅ Ready |
| `GET /api/v1/plants` | Paginated catalogue, field names match Flutter `Plant` | ✅ Ready |
| `GET /api/v1/plants/{plant_id}` | Full profile, `sections: Map<String,String>`, `sources: [{title, url}]` | ✅ Ready |
| `GET /api/v1/districts` | 28 districts, by_region grouping matches locale_data.dart | ✅ Ready |
| `GET /api/v1/districts/{id}` | Single district by integer ID | ✅ Ready |

---

## 6. Tests Performed and Results

### Backend test suite (task-4716)

```
pytest -v  →  368 passed in 15.85s  (0 failures, 0 errors, 0 skipped)
```

**Tests cover:**
- Anonymous auth creation, token hashing, isolation
- Identification submission (authenticated and anonymous), idempotency
- Identification history listing, detail retrieval, anti-IDOR
- Catalogue listing, search, filtering, pagination
- Plant detail retrieval, sections, sources
- District listing and filtering by region
- Image upload validation (format, size, decompression bomb)
- Transport security headers
- Rate limiting and burst behaviour
- Database readiness verification

### Flutter tests

Flutter tests in `test/` were not run — the instructions prohibit modifying or running frontend tests. The test directory was not inspected.

### Manual contract verification

All response schemas were verified by cross-reading:
- `lib/models.dart` field names and types
- `backend/app/schemas/plant.py`
- `backend/app/schemas/identification.py`
- `backend/app/schemas/auth.py`
- `backend/app/schemas/history.py`
- `backend/app/schemas/district.py`
- `backend/app/core/seed.py` (for data correctness)

---

## 7. Backend Files Modified

**None.** The backend was already fully compatible. No backend files were changed during Phase 5.

---

## 8. Remaining Limitations

| Area | Limitation | Resolution path |
|---|---|---|
| **HTTP connectivity** | Flutter has no HTTP client package installed | Flutter team adds `package:http` (or equivalent) to `pubspec.yaml` |
| **Anonymous auth** | Flutter has no token request or storage logic | Flutter team implements `BackendIdentificationService` with token lifecycle |
| **Identification** | `DemoIdentificationService` is hardcoded in `main.dart` line 354 | Flutter team replaces with `BackendIdentificationService` instance; `IdentificationService` interface is already the correct abstraction |
| **`isDemo` mapping** | Backend returns `provider.is_demo` (nested); Flutter needs `IdentificationResult.isDemo` (top-level) | Flutter `BackendIdentificationService` extracts `response['provider']['is_demo']` on parse — no backend change needed |
| **Catalogue** | Flutter uses local `plants` list; backend catalogue not consulted | Optional: Flutter team can call `GET /api/v1/plants` to refresh; local fallback always works |
| **Districts** | Flutter uses local `districtsByRegion` from `locale_data.dart`; backend not consulted | Optional: `GET /api/v1/districts` available when needed |
| **History sync** | Flutter `Discovery` and backend `IdentificationRequest` are independent data stores | By design: no sync layer needed for current scope |
| **Pl@ntNet API** | Live identification requires a valid `PLANTNET_API_KEY` in backend `.env` | Backend team / operator provides key; deterministic mock works for development |
| **Catalogue images** | `photo_asset` paths are Flutter asset bundle paths; no image CDN | By design: images are local assets |

---

## 9. Integration Blockers Requiring Frontend Team Action

The following items require a Flutter-side implementation to complete integration. They cannot be resolved through backend changes.

### Blocker 1 — No HTTP client package
**File:** `pubspec.yaml`  
**Gap:** `package:http` (or `package:dio`) is not in the dependency list.  
**Smallest required change:** Add `http: ^1.2.0` (or equivalent) to `pubspec.yaml` `dependencies`.

### Blocker 2 — No backend identification service
**File:** `lib/models.dart`  
**Gap:** `IdentificationService` has only one implementation: `DemoIdentificationService`. There is no network implementation.  
**Smallest required change:** Add a `BackendIdentificationService` class (new file or added to `models.dart`) implementing the existing `IdentificationService` interface. The interface signature `Future<IdentificationResult> identify(String? photoPath, DemoOutcome outcome)` requires no changes.

### Blocker 3 — `DemoIdentificationService` hardcoded at the injection site
**File:** `lib/main.dart`, line 354  
**Gap:** `IdentifyScreen(store: s, service: DemoIdentificationService())` hardcodes the demo service.  
**Smallest required change:** Replace `DemoIdentificationService()` with an instance of `BackendIdentificationService` (or a service that wraps both with a network-available check for graceful degradation).

### Blocker 4 — No anonymous token issuance or storage
**Gap:** No code calls `POST /api/v1/auth/anonymous` or stores the returned `device_token`.  
**Smallest required change:** On first launch, call `POST /api/v1/auth/anonymous`, store the `device_token` in `SharedPreferences` using a stable key (e.g. `floramw_device_token`), and read it back on subsequent launches.

---

## 10. Git Verification

Final `git status --short` output (all backend, zero Flutter):

```
 M backend/.env.example
 M backend/CONTRACT_ML_INTEGRATION.md
 M backend/app/api/v1/api.py
 M backend/app/api/v1/identification_history.py
 M backend/app/api/v1/identifications.py
 M backend/app/api/v1/plants.py
 M backend/app/core/config.py
 M backend/app/core/readiness.py
 M backend/app/identification/image_validation.py
 M backend/app/identification/service.py
 M backend/app/main.py
 M backend/app/models/user.py
 M backend/app/schemas/identification.py
 M backend/app/schemas/plant.py
 M backend/tests/conftest.py
 M backend/tests/test_*.py
?? backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md
?? backend/FLORAMW_PHASE4_*.md
?? backend/FLORAMW_PHASE5_INTEGRATION_REPORT.md
?? backend/alembic/versions/0006_add_device_token_hash_to_users.py
?? backend/app/api/v1/auth.py
?? backend/app/core/auth.py
?? backend/app/core/middleware.py
?? backend/app/core/rate_limit/
?? backend/app/schemas/auth.py
?? backend/tests/test_auth_and_history.py
?? backend/tests/test_rate_limiting.py
?? backend/tests/test_transport_and_upload_security.py
?? docs/PHASE_4_2_SECURITY_ASSESSMENT.md
```

**No Flutter files (`lib/`, `test/`, `pubspec.yaml`, `android/`, `ios/`) appear in git status.**  
**Nothing was staged, committed, or pushed.**  
**All user modifications were preserved.**

---

## 11. Conclusion

The backend is **fully integration-ready**. All API contracts match the Flutter data models exactly. The backend test suite passes at 368/368.

The integration gap is entirely on the Flutter side: no networking code exists in the application. The four blockers above describe the minimum Flutter-side additions required to complete the integration. They are **additions only** — no existing Flutter UI, model, or service interface needs to be restructured.

**Stop. Awaiting explicit approval before any further action.**

