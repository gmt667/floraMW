# FloraMW — Phase 4.6: Backend Integration Readiness Report

**Date:** 2026-11-15  
**Repository:** `floraMW`  
**Branch:** `backend`  
**Phase:** 4.6 — Backend Integration Readiness  

---

## 1. Executive Summary

Phase 4.6 assessed the FloraMW backend for integration readiness gaps, made two targeted corrections, and produced a comprehensive integration guide for Flutter and other HTTP consumers.

The backend was found to be **substantially ready** for integration. All endpoints return consistent, well-typed responses. Authentication is in place. API contracts align exactly with the Flutter `lib/models.dart` and `lib/locale_data.dart` data models. Rate limiting, security headers, upload validation, and idempotency are all operational.

Three targeted improvements were made:

| # | File | Change | Rationale |
|---|---|---|---|
| 1 | `backend/.env.example` | Expanded template to cover all Phase 4.2–4.3 settings | CORS, HSTS, rate-limiting, upload limits, and confidence thresholds were missing, making the template insufficient for new deployments |
| 2 | `backend/app/api/v1/identification_history.py` | Updated module docstring to reflect current Phase 4.3.2 auth (HTTP 401) instead of old Phase 3.1 HTTP 503 comment | Stale documentation would mislead integrators about endpoint behaviour |
| 3 | `backend/app/api/v1/identification_history.py` | Removed dead `_AUTH_PENDING_MESSAGE` constant (defined but never referenced since Phase 4.3.4) | Dead code |
| 4 | `backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md` | Created comprehensive integration guide | Deliverable: single reference document for all integration consumers |

Zero features were added or rebuilt. No existing tests were modified. No Flutter files were touched.

---

## 2. Integration-Readiness Assessment by Area

### A. API Contract Consistency ✅

| Contract | Status | Detail |
|---|---|---|
| Catalogue response field names | **Aligned** | `id`, `name`, `scientific`, `family`, `category`, `symbol`, `description`, `photo_asset` match `Plant` in `lib/models.dart` exactly |
| Sections format | **Aligned** | `sections: Map<String,String>` returned as `{"section_key": "content"}` matching Flutter `Map<String, String>` |
| Sources format | **Aligned** | `{"title": "…", "url": "…"}` matching Flutter `PlantSource(this.title, this.url)` |
| District names | **Aligned** | All 28 district names match `lib/locale_data.dart` `districtsByRegion` exactly |
| Identification `candidate_ids` | **Aligned** | `candidate_ids: List[str]` on `IdentificationResponse` matches `IdentificationResult.candidateIds` in Flutter |
| `provider.is_demo` | **Aligned** | Maps directly to Flutter `IdentificationResult.isDemo` |
| Plant slug IDs | **Aligned** | `hibiscus`, `periwinkle`, `marigold`, `frangipani` match Flutter `Plant.id` values |
| Auth response | **Consistent** | `user_id`, `device_token`, `token_type`, `role`, `is_anonymous`, `created_at` |
| History response | **Consistent** | Pagination fields (`total`, `page`, `limit`, `total_pages`, `has_more`, `items`) consistent across catalogue, plant, and history list endpoints |

### B. Endpoint Availability ✅

All endpoints return appropriate HTTP status codes and are reachable:

| Endpoint | Method | Auth | HTTP (success) | HTTP (errors) |
|---|---|---|---|---|
| `/` | GET | None | 200 | — |
| `/health` | GET | None | 200 | — |
| `/api/v1/auth/anonymous` | POST | None | 201 | 500 |
| `/api/v1/identifications` | POST | Optional | 200 / 201 | 400, 413, 415, 422, 429, 502, 503, 504 |
| `/api/v1/identifications` | GET | Required | 200 | 401 |
| `/api/v1/identifications/{id}` | GET | Required | 200 | 401, 404 |
| `/api/v1/plants` | GET | None | 200 | 422 |
| `/api/v1/plants/{plant_id}` | GET | None | 200 | 404, 422 |
| `/api/v1/districts` | GET | None | 200 | — |
| `/api/v1/districts/{id}` | GET | None | 200 | 404 |

### C. Error Handling ✅

| Scenario | Behaviour |
|---|---|
| Invalid image format | HTTP 415 `image_format_unsupported` |
| Oversized image | HTTP 413 `image_too_large` |
| Decompression bomb | HTTP 422 `image_dimensions_exceeded` |
| Rate limit exceeded | HTTP 429 `rate_limit_exceeded` with `Retry-After` header |
| Missing auth | HTTP 401 `authentication_required` |
| Invalid/expired token | HTTP 401 `authentication_failed` |
| Cross-user access | HTTP 404 (anti-IDOR — existence not disclosed) |
| Plant slug not found | HTTP 404 |
| Provider unavailable | HTTP 503 `provider_unavailable` (retryable) |
| Provider timeout | HTTP 504 `provider_timeout` (retryable) |
| Provider config error | HTTP 503 `identification_disabled` (not retryable) |
| All errors | Never expose internal paths, stack traces, secrets, or user IDs |

### D. Backend Configuration ✅ (gap fixed)

`.env.example` was expanded from 39 lines to 121 lines to fully cover all configurable settings introduced through Phase 4.3:

**Previously missing from `.env.example`:**
- `CORS_ORIGINS`, `CORS_ALLOW_CREDENTIALS`
- `ENABLE_HSTS`, `HSTS_MAX_AGE_SECONDS`
- `MAX_UPLOAD_SIZE_BYTES`, `MAX_IMAGE_DIMENSION_PX`, `MAX_IMAGE_TOTAL_PIXELS`, `UPLOAD_STREAM_CHUNK_SIZE`
- `RATE_LIMIT_*` (12 settings)
- `CONFIDENCE_THRESHOLD_*` (3 settings)
- `IDENTIFICATION_PROCESSING_LEASE_SECONDS`

### E. Integration Documentation ✅ (created)

`backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md` was created covering:
- Base URL configuration by environment
- Complete endpoint inventory with HTTP methods, auth requirements, rate limits
- Request and response examples for every endpoint
- Flutter field mapping table (`candidate_ids`, `is_demo`, `photo_asset`, sections/sources format)
- Authentication flow with token lifecycle notes
- Image upload constraints
- Error response convention and all error codes
- Security headers
- Environment configuration reference with minimum production overrides
- Database migration procedure
- Remaining integration limitations

---

## 3. Configuration Requirements

### Development (default `.env`)
```dotenv
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///floramw.db
IDENTIFICATION_PROVIDER=deterministic
ALLOW_MOCK_PROVIDER=true
CORS_ORIGINS=["*"]
CORS_ALLOW_CREDENTIALS=false
ENABLE_HSTS=false
RATE_LIMIT_STORAGE=memory
```

### Production (minimum overrides)
```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/floramw
CORS_ORIGINS=["https://app.floramw.example.com"]
CORS_ALLOW_CREDENTIALS=true
ENABLE_HSTS=true
IDENTIFICATION_PROVIDER=plantnet
ALLOW_MOCK_PROVIDER=false
PLANTNET_API_KEY=<key>
RATE_LIMIT_STORAGE=redis
RATE_LIMIT_REDIS_URL=redis://redis-host:6379/0
RATE_LIMIT_TRUST_PROXY_HEADERS=true
```

---

## 4. Tests Executed and Results

### Pre-change baseline (task-4663)
```
pytest -v  →  368 passed in 16.47s  (0 failures, 0 errors, 0 skipped)
```

### Post-change targeted regression (task-4690)
```
pytest tests/test_auth_and_history.py -v  →  19 passed in 2.36s
```

Linting:
```
ruff check app/api/v1/identification_history.py  →  All checks passed!
```

No test failures. No new tests were required — no logic was changed.

---

## 5. Files Modified

| File | Change |
|---|---|
| `backend/.env.example` | Expanded from 39 → 121 lines; added all Phase 4.2–4.3 configuration settings |
| `backend/app/api/v1/identification_history.py` | Updated stale module docstring; removed dead `_AUTH_PENDING_MESSAGE` constant |
| `backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md` | **Created** — comprehensive backend integration reference |
| `backend/FLORAMW_PHASE4_6_INTEGRATION_READINESS_REPORT.md` | **Created** — this report |

**Zero Flutter files were modified** (`lib/`, `pubspec.yaml`, `test/`, `android/`, `ios/`).  
**Zero user modifications were overwritten** (`CONTRACT_ML_INTEGRATION.md`, `test_phase3_1_1.py` both preserved).  
**Nothing was staged, committed, or pushed.**

---

## 6. Git Status Verification

```
 M backend/.env.example
 M backend/app/api/v1/identification_history.py
 M backend/CONTRACT_ML_INTEGRATION.md        ← user modification, preserved
 M backend/app/api/v1/api.py                 ← prior phase work
 M backend/app/api/v1/identifications.py     ← prior phase work
 M backend/app/api/v1/plants.py              ← prior phase work
 M backend/app/core/config.py                ← prior phase work
 M backend/app/core/readiness.py             ← prior phase work
 M backend/app/identification/image_validation.py  ← prior phase work
 M backend/app/identification/service.py     ← prior phase work
 M backend/app/main.py                       ← prior phase work
 M backend/app/models/user.py                ← prior phase work
 M backend/app/schemas/identification.py     ← prior phase work
 M backend/app/schemas/plant.py              ← prior phase work
 M backend/tests/conftest.py                 ← prior phase work
 M backend/tests/test_*.py                   ← prior phase work
?? backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md   ← new Phase 4.6
?? backend/FLORAMW_PHASE4_6_INTEGRATION_READINESS_REPORT.md ← new Phase 4.6
?? backend/alembic/versions/0006_add_device_token_hash_to_users.py ← prior phase
?? backend/app/api/v1/auth.py                ← prior phase
?? backend/app/core/auth.py                  ← prior phase
?? backend/app/core/middleware.py            ← prior phase
?? backend/app/core/rate_limit/              ← prior phase
?? backend/app/schemas/auth.py               ← prior phase
?? backend/tests/test_auth_and_history.py    ← prior phase
?? backend/tests/test_rate_limiting.py       ← prior phase
?? backend/tests/test_transport_and_upload_security.py ← prior phase
?? docs/PHASE_4_2_SECURITY_ASSESSMENT.md     ← prior phase

No Flutter files appear in git status. ✅
```

---

## 7. Remaining Integration Limitations

| Area | Limitation |
|---|---|
| **Online identification** | Requires a live Pl@ntNet API key and internet connectivity. The current deterministic mock provider is dev/test only. |
| **Catalogue images** | `photo_asset` values are Flutter bundle paths; no image CDN or HTTP image-serving endpoint exists yet. |
| **Discovery sync** | Flutter `Discovery` records are stored locally via `SharedPreferences`. Backend `IdentificationRequest` history is separately persisted per device token. No sync layer exists. |
| **Token loss** | If a device token is lost (reinstall, storage clear), the user must call `POST /api/v1/auth/anonymous` for a new token. Prior history cannot be recovered. |
| **Multi-device** | One token per auth call. A single user identity across multiple devices is not currently supported. |
| **frangipani catalogue matching** | *Plumeria rubra* is in the Flutter catalogue and backend seed but is not included in the deterministic mock provider's candidate output. It will only appear via real Pl@ntNet results. |

---

## 8. Conclusion

Phase 4.6 is **COMPLETE**. The backend is integration-ready. The integration guide at `backend/FLORAMW_BACKEND_INTEGRATION_GUIDE.md` provides a complete, implementation-verified reference for Flutter and any future HTTP consumer.

**Stop. Awaiting explicit approval before proceeding to the next phase.**

