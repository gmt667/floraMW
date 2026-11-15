# FloraMW Backend Integration Guide

**Version:** 0.1.0  
**Branch:** `backend`  
**Last updated:** 2026-11-15  

This document describes how a client (Flutter app or any HTTP consumer) integrates with the FloraMW backend API. It is generated from the actual implementation, not assumed behaviour.

---

## 1. Base URL

The base URL is environment-dependent.  Configure it in the Flutter app's service layer, **not** hardcoded in UI code.

| Environment | Example base URL |
|---|---|
| Local development | `http://localhost:8000` |
| Local network (device) | `http://192.168.x.x:8000` |
| Staging / Production | `https://api.floramw.example.com` |

All endpoints are rooted at `/api/v1`.

---

## 2. Endpoint Inventory

### 2.1 Service & Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/` | None | Service info (name, version, environment, docs URL) |
| `GET` | `/health` | None | Database connectivity health check |
| `GET` | `/docs` | None | Interactive Swagger UI (development) |
| `GET` | `/redoc` | None | ReDoc documentation (development) |
| `GET` | `/api/v1/openapi.json` | None | OpenAPI 3.1 schema |

**Health response example:**
```json
{
  "status": "healthy",
  "database": "connected",
  "version": "0.1.0",
  "environment": "development"
}
```

---

### 2.2 Authentication

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| `POST` | `/api/v1/auth/anonymous` | None | 10 req/min, burst 20 | Issue anonymous device token |

#### `POST /api/v1/auth/anonymous`

Creates a new anonymous device identity and returns a one-time raw token. The token must be stored securely on-device; it is **never re-issued**.

**Request:** No body required.

**Response `201 Created`:**
```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "device_token": "a3f...64-hex-character-token...b9c",
  "token_type": "bearer",
  "role": "guest",
  "is_anonymous": true,
  "created_at": "2026-11-15T10:00:00Z"
}
```

**Client responsibility:** Store `device_token` in secure local storage. Use it in all subsequent requests as `Authorization: Bearer <device_token>`.

**Error `500`:** Returned only on a database collision (astronomically rare with 256-bit entropy).

---

### 2.3 Plant Identification

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| `POST` | `/api/v1/identifications` | Optional | 5 req/min, burst 15 | Submit image for plant identification |

#### `POST /api/v1/identifications`

Accepts a multipart image upload and returns structured identification candidates.

**Request headers:**
| Header | Required | Description |
|---|---|---|
| `Content-Type` | Yes | `multipart/form-data` |
| `Authorization` | Optional | `Bearer <device_token>` — links result to user history |
| `X-Client-Request-Id` | Optional | Client UUID for idempotency (deduplicated per user+key) |

**Request form fields:**
| Field | Type | Required | Description |
|---|---|---|---|
| `image` | binary file | Yes | JPEG, PNG, or WebP. Max 10 MB. Max 4,096 × 4,096 px. |
| `latitude` | float | No | Geographic latitude (−90 to 90) |
| `longitude` | float | No | Geographic longitude (−180 to 180) |

**Response `200 OK` / `201 Created`:**
```json
{
  "outcome": "MATCH",
  "candidates": [
    {
      "scientific_name": "Hibiscus rosa-sinensis",
      "common_names": ["Chinese Hibiscus"],
      "confidence": 0.88,
      "confidence_level": "high",
      "family": "Malvaceae",
      "genus": "Hibiscus",
      "catalogue_matched": true,
      "catalogue_plant_id": "hibiscus",
      "provider_notes": null
    }
  ],
  "candidate_ids": ["hibiscus", "periwinkle", "marigold"],
  "top_confidence_level": "high",
  "photo_guidance": null,
  "provider": {
    "provider_id": "mock",
    "model_version": "mock-v1",
    "is_demo": true
  },
  "safety_disclaimer": "Plant identification from photographs is not a substitute for expert botanical assessment…",
  "client_request_id": "550e8400-e29b-41d4-a716-446655440001",
  "created_at": "2026-11-15T10:00:00Z"
}
```

**Key fields for Flutter integration:**

| Field | Flutter mapping |
|---|---|
| `candidate_ids` | `IdentificationResult.candidateIds` — direct slug list |
| `provider.is_demo` | `IdentificationResult.isDemo` |
| `outcome` | `"MATCH"`, `"NO_MATCH"`, or `"DEMO_MODE"` |
| `safety_disclaimer` | Must be displayed to users |

**Outcome values:**
| Value | Meaning |
|---|---|
| `MATCH` | Real candidates returned |
| `NO_MATCH` | Provider found no matching species |
| `DEMO_MODE` | Deterministic mock provider used |

**Error responses:**
| HTTP | `error_code` | Meaning |
|---|---|---|
| `400` | `image_empty` | Zero-byte upload |
| `400` | `image_decoding_failed` | Corrupted or unreadable file |
| `413` | `image_too_large` | Exceeds 10 MB limit |
| `415` | `image_format_unsupported` | Not JPEG / PNG / WebP |
| `422` | `image_dimensions_exceeded` | Pixel dimensions or decompression bomb risk |
| `422` | `request_validation_failed` | Invalid form fields or headers |
| `429` | `rate_limit_exceeded` | Too many requests |
| `502` | `provider_error` | Provider returned invalid response |
| `503` | `provider_unavailable` | Provider not reachable |
| `503` | `identification_disabled` | No provider configured for this environment |
| `504` | `provider_timeout` | Provider timed out |

**All error responses share this structure:**
```json
{
  "detail": {
    "error_code": "image_too_large",
    "message": "The uploaded file is too large. Maximum allowed size is 10 MB.",
    "retryable": false,
    "safety_disclaimer": "Plant identification from photographs…"
  }
}
```

---

### 2.4 Identification History

Both history endpoints require authentication.

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/identifications` | Required | Paginated identification history (caller's own records only) |
| `GET` | `/api/v1/identifications/{id}` | Required | Full identification detail + candidates |

**Authentication failure:** `HTTP 401` with `error_code: authentication_required` or `authentication_failed`.

**Cross-user access:** `HTTP 404` (anti-IDOR — another user's record existence is never disclosed).

#### `GET /api/v1/identifications`

**Query parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `page` | int | `1` | Page number (1-based) |
| `limit` | int | `20` | Items per page (1–100) |
| `outcome` | string | — | Filter: `MATCH`, `NO_MATCH`, `DEMO_MODE` |
| `provider_id` | string | — | Filter by provider name |
| `model_version` | string | — | Filter by model version |
| `created_after` | ISO 8601 | — | Records created after this timestamp |
| `created_before` | ISO 8601 | — | Records created before this timestamp |

**Response `200`:**
```json
{
  "total": 42,
  "page": 1,
  "limit": 20,
  "total_pages": 3,
  "has_more": true,
  "items": [
    {
      "id": "550e8400-...",
      "client_request_id": "...",
      "outcome": "MATCH",
      "top_confidence_level": "high",
      "provider_id": "mock",
      "model_version": "mock-v1",
      "image_format": "image/jpeg",
      "image_size_bytes": 204800,
      "candidate_count": 3,
      "created_at": "2026-11-15T10:00:00Z"
    }
  ]
}
```

#### `GET /api/v1/identifications/{id}`

Returns full detail including all candidates. `HTTP 404` if not owned by caller or does not exist.

---

### 2.5 Plant Catalogue

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/plants` | None | 60 req/min, burst 120 | Browse / search plant catalogue |
| `GET` | `/api/v1/plants/{plant_id}` | None | 60 req/min, burst 120 | Full botanical profile by slug |

**All field names match `lib/models.dart` exactly.**

#### `GET /api/v1/plants`

**Query parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | — | Full-text search (name, scientific name, family). Max 100 chars. |
| `category` | string | — | Filter by category (e.g. `"Garden flowers"`, `"Research interest"`) |
| `family` | string | — | Filter by botanical family (e.g. `"Apocynaceae"`) |
| `sort` | string | `name_asc` | `"name_asc"` or `"name_desc"` |
| `page` | int | `1` | Page number (1-based) |
| `limit` | int | `20` | Items per page (1–100) |

**Response `200`:**
```json
{
  "total": 4,
  "page": 1,
  "limit": 20,
  "total_pages": 1,
  "has_more": false,
  "items": [
    {
      "id": "hibiscus",
      "name": "Chinese hibiscus",
      "scientific": "Hibiscus rosa-sinensis",
      "family": "Malvaceae",
      "category": "Garden flowers",
      "symbol": "🌺",
      "description": "A tropical evergreen shrub in the mallow family…",
      "photo_asset": "assets/plants/hibiscus.jpg"
    }
  ]
}
```

**Catalogue plant IDs (slugs):**

| Slug | Common name | Scientific name | Category |
|---|---|---|---|
| `hibiscus` | Chinese hibiscus | *Hibiscus rosa-sinensis* | Garden flowers |
| `periwinkle` | Madagascar periwinkle | *Catharanthus roseus* | Research interest |
| `marigold` | African marigold | *Tagetes erecta* | Garden flowers |
| `frangipani` | Frangipani | *Plumeria rubra* | Flowering trees |

> [!IMPORTANT]
> `photo_asset` values (e.g. `"assets/plants/hibiscus.jpg"`) are Flutter asset bundle paths. They resolve inside the mobile app bundle, not as HTTP URLs from this API.

#### `GET /api/v1/plants/{plant_id}`

Returns the full botanical profile including sections (`Map<String, String>`) and sources (`List<PlantSource>`), matching the Flutter `Plant` model exactly.

**Response `200`:**
```json
{
  "id": "hibiscus",
  "name": "Chinese hibiscus",
  "scientific": "Hibiscus rosa-sinensis",
  "family": "Malvaceae",
  "category": "Garden flowers",
  "symbol": "🌺",
  "description": "A tropical evergreen shrub in the mallow family…",
  "photo_asset": "assets/plants/hibiscus.jpg",
  "sections": {
    "Identifying features": "Large funnel-shaped flowers…",
    "Growing conditions": "NC State Extension describes sun to partial shade…"
  },
  "section_details": [ /* provenance metadata — for admin/review use */ ],
  "sources": [
    { "title": "NC State Extension · Chinese hibiscus", "url": "https://…", "is_pmra_reference": false }
  ],
  "verified_districts": []
}
```

**Error `404`:** Plant slug not found or not published.  
**Error `422`:** Slug too long (> 64 characters).

---

### 2.6 Malawi Administrative Districts

| Method | Path | Auth | Rate limit | Description |
|---|---|---|---|---|
| `GET` | `/api/v1/districts` | None | 60 req/min, burst 120 | All 28 Malawi districts, optionally filtered by region |
| `GET` | `/api/v1/districts/{id}` | None | 60 req/min, burst 120 | Single district by integer ID |

**Query parameter:** `region` — `"Northern"`, `"Central"`, or `"Southern"`.

**District names match `lib/locale_data.dart` exactly:**
- **Northern (6):** Chitipa, Karonga, Likoma, Mzimba, Nkhata Bay, Rumphi  
- **Central (9):** Dedza, Dowa, Kasungu, Lilongwe, Mchinji, Nkhotakota, Ntcheu, Ntchisi, Salima  
- **Southern (13):** Balaka, Blantyre, Chikwawa, Chiradzulu, Machinga, Mangochi, Mulanje, Mwanza, Neno, Nsanje, Phalombe, Thyolo, Zomba  

**Response `200`:**
```json
{
  "total": 28,
  "items": [
    { "id": 1, "name": "Chitipa", "region": "Northern" }
  ],
  "by_region": {
    "Northern": ["Chitipa", "Karonga", "Likoma", "Mzimba", "Nkhata Bay", "Rumphi"],
    "Central": ["Dedza", "Dowa", "Kasungu", "Lilongwe", "Mchinji", "Nkhotakota", "Ntcheu", "Ntchisi", "Salima"],
    "Southern": ["Balaka", "Blantyre", "Chikwawa", "Chiradzulu", "Machinga", "Mangochi", "Mulanje", "Mwanza", "Neno", "Nsanje", "Phalombe", "Thyolo", "Zomba"]
  }
}
```

---

## 3. Authentication Reference

### Bearer token flow

```
1. POST /api/v1/auth/anonymous   →  device_token (store securely)
2. All protected requests:          Authorization: Bearer <device_token>
3. Token is valid indefinitely.     Re-register on a fresh install if lost.
```

### Authentication error codes

| `error_code` | Situation |
|---|---|
| `authentication_required` | No `Authorization` header on a protected endpoint |
| `authentication_failed` | Malformed header, unknown token, or expired token |

---

## 4. Required Request Headers

| Header | Endpoints | Description |
|---|---|---|
| `Content-Type: multipart/form-data` | `POST /api/v1/identifications` | Required for image upload |
| `Authorization: Bearer <token>` | History endpoints (required); Identification (optional) | Device token from anonymous auth |
| `X-Client-Request-Id: <uuid>` | `POST /api/v1/identifications` | Optional idempotency key (UUID v4 recommended) |

---

## 5. Image Upload Requirements

| Constraint | Value |
|---|---|
| Accepted formats | JPEG (`image/jpeg`), PNG (`image/png`), WebP (`image/webp`) |
| Maximum file size | 10 MB |
| Maximum dimensions | 4,096 × 4,096 pixels |
| Minimum file size | 1 KB |
| Content-Type | Must be `multipart/form-data`; form field name must be `image` |
| Decompression bomb | Images exceeding 25 megapixels total are rejected (HTTP 422) |

Images are validated by magic bytes (not declared MIME type). Spoofed file extensions are rejected.

---

## 6. Error Response Convention

All API errors follow a consistent structure. HTTP 4xx / 5xx responses from identification and auth endpoints include a `detail` object:

```json
{
  "detail": {
    "error_code": "<stable_code>",
    "message": "<user-safe description>",
    "retryable": true,
    "safety_disclaimer": "<plant safety statement>"
  }
}
```

Standard FastAPI validation errors (`HTTP 422` from query param or body schema failures) use FastAPI's default `{"detail": [...]}` format.

**Rate limit responses** (`HTTP 429`) include:
- `Retry-After` header (seconds until quota resets)
- `X-RateLimit-Limit` header (request limit)
- `X-RateLimit-Remaining` header (remaining requests in window)

---

## 7. Security Headers

All responses include:

| Header | Value |
|---|---|
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Strict-Transport-Security` | Emitted only over HTTPS when `ENABLE_HSTS=true` or `ENVIRONMENT=production` |

---

## 8. Environment Configuration

Copy `.env.example` to `.env` and set values appropriate for the target environment. The application loads `.env` automatically via `pydantic-settings`.

**Minimum production overrides:**

```dotenv
ENVIRONMENT=production
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/floramw
CORS_ORIGINS=["https://app.floramw.example.com"]
CORS_ALLOW_CREDENTIALS=true
ENABLE_HSTS=true
IDENTIFICATION_PROVIDER=plantnet
ALLOW_MOCK_PROVIDER=false
PLANTNET_API_KEY=<your_key>
RATE_LIMIT_STORAGE=redis
RATE_LIMIT_REDIS_URL=redis://redis-host:6379/0
RATE_LIMIT_TRUST_PROXY_HEADERS=true
```

> [!CAUTION]
> Never commit `.env` with real credentials. `.env` is listed in `.gitignore`. Only `.env.example` belongs in source control.

> [!WARNING]
> `ALLOW_MOCK_PROVIDER=true` and `IDENTIFICATION_PROVIDER=deterministic` must **not** be set in production. The backend automatically enforces this and returns `HTTP 503` if the deterministic provider is used in `ENVIRONMENT=production`.

---

## 9. Database Migration

Before the first startup (or after any schema change), run:

```bash
cd backend
alembic upgrade head
```

The application verifies on startup that the database is at the current Alembic head. A mismatch raises a `DatabaseReadinessError` and prevents the server from accepting traffic.

**Current migration head:** `0006_add_device_token_hash_to_users`

---

## 10. Starting the Backend

```bash
cd backend
alembic upgrade head           # apply migrations
uvicorn app.main:app --reload  # development with hot reload
```

For production:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

## 11. Remaining Integration Limitations

| Area | Limitation | Note |
|---|---|---|
| Offline identification | Flutter currently uses `DemoIdentificationService` exclusively. Real network identification requires a live backend and internet connectivity. | Pl@ntNet API key required for production. |
| Catalogue images | `photo_asset` paths are Flutter bundle assets, not API-served URLs. The backend has no image-serving endpoint. | Bundle-side only. |
| Identified record sync | `Discovery` records are currently stored locally in Flutter (`AppStore` via `SharedPreferences`). Backend history is independently persisted per authenticated device. | No sync layer yet. |
| Token expiry | Anonymous tokens do not expire by design. If a token is lost (e.g. app reinstall), a new token must be issued via `POST /api/v1/auth/anonymous`. History is not migrated. | By design for offline-first. |
| Multi-device | One token per `POST /api/v1/auth/anonymous` call. Multiple device tokens for one user are not currently supported. | Future consideration. |

