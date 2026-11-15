# FloraMW — Phase 4.4: Backend Catalogue API Readiness Report

**Repository:** `C:\Users\rosem\Desktop\my projects\floraMW`  
**Branch:** `backend`  
**Execution Date:** 2026-11-15  
**Final Status:** **PASS**

---

## 1. Executive Summary

Phase 4.4 evaluated, enhanced, and verified the readiness of the FloraMW Botanical Catalogue API for future integration with the existing Flutter application.

Key achievements:
- **Zero Frontend Impact:** The Flutter frontend remained strictly read-only (0 files modified in `lib/`, `pubspec.yaml`, `test/`, `android/`, `ios/`, assets, or platform files).
- **Exact Contract Alignment:** Ensured all catalogue field names, data structures, and response shapes mirror the Flutter application's models (`lib/models.dart`) without deviation.
- **Enhanced Catalogue Filtering & Security:** Added dedicated `family` filtering, query parameter bounds validation (`max_length` limits), and slug length sanitization on plant details.
- **Data Integrity Verified:** Confirmed the integrity, uniqueness, and consistency of all 4 seeded reference plants (`hibiscus`, `periwinkle`, `marigold`, `frangipani`), 36 botanical sections, 13 sources, and 28 administrative districts of Malawi.
- **Privacy & Information Protection:** Verified that no internal user data, reviewer IDs (`verified_by`), or administrative tokens are disclosed through the public catalogue endpoints.
- **100% Test Pass Rate:** Added 9 new focused catalogue tests. All 364 tests across the entire backend test suite passed with 0 failures, 0 errors, and 0 skips.
- **Code Quality:** All modified and newly created backend files pass `ruff check` with 0 warnings or errors.

---

## 2. Existing Functionality Inspected

The following existing catalogue components and contracts were inspected prior to making any modifications:

1. **Database Models (`app/models/plant.py`, `app/models/district.py`)**:
   - `Plant`: Core botanical table with stable slug primary key `id` (e.g. `hibiscus`), unique `scientific_name`, `common_name_en`, `family`, `category`, `symbol`, `description`, `is_published`, timestamps.
   - `PlantSection`: Botanical profile sections with composite unique constraint `uq_plant_section_key(plant_id, section_key)`, verification status, and provenance citations.
   - `PlantSource`: Bibliographic citations (`title`, `url`, `is_pmra_reference`).
   - `PlantDistribution`: District-level occurrences in Malawi linked to `District(id, name, region)`.
2. **Pydantic Schemas (`app/schemas/plant.py`, `app/schemas/district.py`)**:
   - `PlantSummaryOut`: Matches frontend `Plant` model fields (`id`, `name`, `scientific`, `family`, `category`, `symbol`, `description`, `photo_asset`).
   - `PlantDetailOut`: Extends `PlantSummaryOut` with `sections` (`Map<String, String>`), `sources` (`List<PlantSource>`), `section_details`, and `verified_districts`.
   - `PlantListResponse`: Standard pagination envelope (`total`, `page`, `limit`, `total_pages`, `has_more`, `items`).
   - `DistrictOut` & `DistrictListResponse`: Full 28-district catalog with regional groupings (`Northern`, `Central`, `Southern`).
3. **Frontend Ground Truth (`lib/models.dart`, `lib/locale_data.dart`, `lib/main.dart`)**:
   - Verified that Flutter searches across `${p.name} ${p.scientific} ${p.family}`, filters by `category` (`'All plants'` means unfiltered), and sorts by `name` (A-Z or Z-A).
   - Preserved all technical identifiers: `plant`, `plant_id`, `matched_plant_id`, `/api/v1/plants`, and `catalogue_plant_id`. No identifiers were renamed to `flower`.

---

## 3. Backend Files Created or Modified

1. **`backend/app/api/v1/plants.py`**:
   - Added `family: Optional[str] = Query(None, description="Filter by botanical family (e.g. 'Apocynaceae')", max_length=100)`.
   - Added `max_length` bounds on query parameters (`q`: 100, `category`: 50) to prevent query string abuse.
   - Added slug length and whitespace sanitization in `get_plant(plant_id)`: whitespace is stripped, and slugs $> 64$ characters immediately return `HTTP 404 Not Found`.
2. **`backend/app/schemas/plant.py`**:
   - Enriched OpenAPI schema field descriptions across `PlantSummaryOut`, `PlantDetailOut`, and `PlantListResponse`.
3. **`backend/tests/test_catalog.py`**:
   - Added 9 new tests covering family filtering, case-insensitive matching, combined category/family filtering, query parameter validation, oversized slug rejection, data integrity verification, and non-disclosure of internal user information.

---

## 4. Catalogue Endpoints Verified

### 4.1 `GET /api/v1/plants` (Browse & Search Catalogue)
- **Path:** `/api/v1/plants`
- **Method:** `GET`
- **Query Parameters:**
  - `q` (string, max 100): Free-text search across English common name, scientific binomial name, and family.
  - `category` (string, max 50): Filter by category (e.g. `'Garden flowers'`, `'Research interest'`, `'Flowering trees'`). `'All plants'` is treated as unfiltered.
  - `family` (string, max 100): Direct filter by taxonomic plant family (e.g. `'Apocynaceae'`, `'Malvaceae'`).
  - `sort` (enum: `'name_asc'`, `'name_desc'`, default `'name_asc'`): Sorts alphabetically by common name. Unsupported values return `HTTP 422 Unprocessable Entity`.
  - `page` (int, $\ge 1$, default 1): Page index.
  - `limit` (int, $1 \dots 100$, default 20): Items per page.
- **Response (`200 OK`):** `PlantListResponse` containing pagination metadata and `List[PlantSummaryOut]`.

### 4.2 `GET /api/v1/plants/{plant_id}` (Retrieve Detailed Botanical Profile)
- **Path:** `/api/v1/plants/{plant_id}`
- **Method:** `GET`
- **Path Parameter:**
  - `plant_id` (string): Stable slug identifier (e.g. `'hibiscus'`, `'periwinkle'`).
- **Response (`200 OK`):** `PlantDetailOut` containing full taxonomy, `sections` dictionary (`Map<String, String>`), `sources` list, and `verified_districts`.
- **Error (`404 Not Found`):** Returned if the plant does not exist, slug exceeds 64 chars, or `is_published` is `False`.

### 4.3 `GET /api/v1/districts` (List Administrative Districts)
- **Path:** `/api/v1/districts`
- **Method:** `GET`
- **Query Parameter:** `region` (optional string: `'Northern'`, `'Central'`, `'Southern'`).
- **Response (`200 OK`):** `DistrictListResponse` with all 28 districts (or filtered subset) and `by_region` dictionary.

### 4.4 `GET /api/v1/districts/{district_id}` (Get Single District)
- **Path:** `/api/v1/districts/{district_id}`
- **Method:** `GET`
- **Response (`200 OK`):** `DistrictOut(id, name, region)`.
- **Error (`404 Not Found`):** Returned if district integer ID is not found.

---

## 5. Data Integrity Findings

Direct database inspection of `floramw.db` and the test database confirmed:
1. **Plant Slugs & Uniqueness:**
   - 4 seeded reference plants with unique IDs: `hibiscus`, `periwinkle`, `marigold`, `frangipani`.
   - All 4 plants have `is_published = True`.
   - All 4 plants have valid scientific binomial names matching the ML botanical matching catalog (`Hibiscus rosa-sinensis`, `Catharanthus roseus`, `Tagetes erecta`, `Plumeria rubra`).
2. **Sections Completeness:**
   - Exactly 36 sections across the 4 plants (9 sections per plant).
   - Every plant includes the 8 standardized sections: `Local names & knowledge`, `Medicinal research`, `Malawi distribution`, `Growing conditions`, `Plant care & treatment`, `Effects & precautions`, `Legal & conservation`, `Sources & review`.
   - Every plant includes `Identifying features`.
3. **Citations & Regulatory References:**
   - 13 total bibliographic sources.
   - Every single plant record includes the mandatory Pharmacy and Medicines Regulatory Authority (PMRA) citation (`https://www.pmra.mw/who-we-are/`) with `is_pmra_reference = True`.
4. **Districts & Regions:**
   - Exactly 28 districts: Northern (6), Central (9), Southern (13), matching Malawi's official administrative divisions and `lib/locale_data.dart`.
5. **Privacy Non-Disclosure:**
   - Verified that neither `/api/v1/plants` nor `/api/v1/plants/{id}` exposes internal user tables, reviewer IDs (`verified_by`), or session tokens.

---

## 6. API Contract Documentation

### 6.1 Example Catalogue List Request & Response
```http
GET /api/v1/plants?category=Garden%20flowers&sort=name_asc HTTP/1.1
Host: api.floramw.mw
```
```json
{
  "total": 2,
  "page": 1,
  "limit": 20,
  "total_pages": 1,
  "has_more": false,
  "items": [
    {
      "id": "marigold",
      "name": "African marigold",
      "scientific": "Tagetes erecta",
      "family": "Asteraceae",
      "category": "Garden flowers",
      "symbol": "🌼",
      "description": "An upright flowering annual with dense flower heads. Despite its common name, it originates from Mexico and Guatemala.",
      "photo_asset": "assets/plants/marigold.jpg"
    },
    {
      "id": "hibiscus",
      "name": "Chinese hibiscus",
      "scientific": "Hibiscus rosa-sinensis",
      "family": "Malvaceae",
      "category": "Garden flowers",
      "symbol": "🌺",
      "description": "A tropical evergreen shrub in the mallow family, known for large flowers with a prominent central floral tube.",
      "photo_asset": "assets/plants/hibiscus.jpg"
    }
  ]
}
```

### 6.2 Example Plant Detail Request & Response
```http
GET /api/v1/plants/hibiscus HTTP/1.1
Host: api.floramw.mw
```
```json
{
  "id": "hibiscus",
  "name": "Chinese hibiscus",
  "scientific": "Hibiscus rosa-sinensis",
  "family": "Malvaceae",
  "category": "Garden flowers",
  "symbol": "🌺",
  "description": "A tropical evergreen shrub in the mallow family, known for large flowers with a prominent central floral tube.",
  "photo_asset": "assets/plants/hibiscus.jpg",
  "sections": {
    "Local names & knowledge": "Malawian names and reported uses are awaiting community verification...",
    "Medicinal research": "No therapeutic claim has been reviewed in this demonstration...",
    "Malawi distribution": "District occurrence, native or introduced status, habitat and altitude have not been verified...",
    "Growing conditions": "NC State Extension describes moist, well-drained soil...",
    "Plant care & treatment": "Water regularly during active growth...",
    "Effects & precautions": "Do not eat or prepare medicine from an unidentified plant...",
    "Legal & conservation": "Malawi's Pharmacy and Medicines Regulatory Authority regulates medicines...",
    "Sources & review": "Public botanical sources checked on 8 November 2026...",
    "Identifying features": "Large solitary flowers with five petals and a long staminal column..."
  },
  "section_details": [
    {
      "section_key": "Identifying features",
      "content": "Large solitary flowers with five petals...",
      "verification_status": "verified",
      "content_disclaimer_type": "educational_summary",
      "source_citation": null
    }
  ],
  "sources": [
    {
      "title": "NC State Extension · Chinese hibiscus",
      "url": "https://plants.ces.ncsu.edu/plants/hibiscus-rosa-sinensis/",
      "is_pmra_reference": false
    },
    {
      "title": "PMRA · mandate and regulated products",
      "url": "https://www.pmra.mw/who-we-are/",
      "is_pmra_reference": true
    }
  ],
  "verified_districts": []
}
```

---

## 7. Tests Added and Updated

In `backend/tests/test_catalog.py`, 9 tests were added:
1. `test_list_plants_filter_by_family`: Verifies filtering by `Apocynaceae` returns `periwinkle` and `frangipani`.
2. `test_list_plants_filter_by_family_case_insensitive`: Verifies family matching is case-insensitive.
3. `test_list_plants_filter_combined_category_and_family`: Verifies combining `category` and `family` filters.
4. `test_list_plants_filter_family_no_match`: Verifies unknown family returns `total=0` and empty items list.
5. `test_list_plants_query_param_validation_max_length`: Verifies `q` exceeding 100 characters returns `HTTP 422`.
6. `test_list_plants_category_max_length`: Verifies `category` exceeding 50 characters returns `HTTP 422`.
7. `test_get_plant_oversized_slug_returns_404`: Verifies slugs $> 64$ characters return `HTTP 404`.
8. `test_catalogue_does_not_leak_user_information`: Confirms absence of any user/auth fields in catalogue responses.
9. `test_catalogue_data_integrity_all_seeded_records`: Verifies structural validity of all seeded plants.

---

## 8. Complete Test-Suite Execution Results

```
============================= test session starts =============================
platform win32 -- Python 3.13.9, pytest-8.4.2, pluggy-1.5.0
plugins: anyio-4.10.0, asyncio-1.4.1.post1
collected 364 items

============================ 364 passed in 15.55s =============================
```

- **Total Tests Collected:** 364
- **Passed:** 364 (100%)
- **Failed:** 0
- **Skipped:** 0
- **Execution Status:** Complete run (no interruptions).

---

## 9. Code Quality (Ruff)

```bash
ruff check app/api/v1/plants.py app/schemas/plant.py tests/test_catalog.py app/api/v1/identifications.py app/api/v1/identification_history.py app/api/v1/api.py app/api/v1/auth.py app/core/auth.py app/schemas/auth.py alembic/versions/0006_add_device_token_hash_to_users.py app/identification/service.py app/core/config.py app/core/readiness.py app/core/rate_limit/limiter.py app/core/rate_limit/middleware.py app/models/user.py app/schemas/identification.py tests/test_auth_and_history.py
All checks passed!
```

---

## 10. Git Status & Compliance

- **Current Branch:** `backend`
- **Cached Changes (`git diff --cached`):** Clean (0 staged files).
- **Flutter Frontend:** Untouched (0 modifications across `lib/`, `pubspec.yaml`, `test/`, `android/`, `ios/`, assets).
- **User Files Preserved:** `backend/CONTRACT_ML_INTEGRATION.md` and user-owned lines in `backend/tests/test_phase3_1_1.py` preserved intact.

---

## 11. Remaining Limitations & Observations

1. **Malawi District Occurrences Pending Verification:**
   Per `lib/models.dart`, district occurrences for the reference plants are currently awaiting field herbarium and community verification (`verified_districts: []`). As field botanical teams verify occurrences in Malawi, rows can be added to `plant_distributions` without modifying the API contract.
2. **Readiness for Flutter Client Connection:**
   The catalogue endpoints are fully ready for integration. When the Flutter app is connected to the backend, it can fetch `/api/v1/plants` and directly populate the existing `Plant` and `PlantSource` Dart models.

---

## 12. Final Verdict

**PASS**

The FloraMW backend catalogue API is fully verified, reliable, documented, and ready for future Flutter client integration.

