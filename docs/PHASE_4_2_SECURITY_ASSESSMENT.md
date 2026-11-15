# FloraMW — Phase 4.2: Read-Only Backend Security Assessment Report

**Assessment Type:** READ-ONLY Architectural & Security Audit  
**Repository:** `C:\Users\rosem\Desktop\my projects\floraMW`  
**Backend:** `C:\Users\rosem\Desktop\my projects\floraMW\backend`  
**Current Branch:** `backend`  
**Current Commit:** `ed97ea4badb318b1d272b675ad588201e5f894bf` (Synchronized with `origin/backend`)  
**Database Schema Target:** Alembic Revision `0005_add_lease_assigned_at_to_identification_requests`  
**Test Baseline:** 254 passing automated tests  

---

## 1. Executive Summary

This assessment provides a comprehensive, read-only security evaluation of the FloraMW backend in preparation for **Phase 4.2: API Security Hardening**. 

The backend has established high-integrity foundations in prior phases: two-phase database reservations, lease fencing with optimistic locking, candidate rank uniqueness constraints, metadata stripping on uploaded images, and fail-closed security for unauthenticated history endpoints. 

However, this audit identifies critical security and operational vulnerabilities that must be addressed before exposure to public internet traffic:
1. **Unthrottled Identification Ingestion:** `POST /api/v1/identifications` possesses zero rate limiting or concurrency throttling. An unauthenticated attacker or client retry loop can exhaust external Pl@ntNet API quotas, saturate worker CPU/RAM with decompression workloads, and degrade server availability.
2. **Missing In-Flight Request Size Ceiling:** FastAPI reads the full request payload into memory (`await image.read()`) before size verification executes in `validate_and_prepare`, creating a memory-exhaustion vector under multi-megabyte streaming uploads.
3. **Idempotency Bypass on Omitted Headers:** When `X-Client-Request-Id` is omitted, the server dynamically generates a random UUID, bypassing the database deduplication cache and triggering a full upstream API call for every submission, even for identical images.
4. **Authentication Vacuum vs. Offline-First Constraints:** While `GET /api/v1/identifications` is securely fail-closed (HTTP 503), neither the backend nor the Flutter frontend implements user registration, login, or token exchange. Introducing rigid cloud-only authentication would break offline field observations in rural Malawi.
5. **Lack of Standard Security Headers:** The FastAPI application registers only `CORSMiddleware`. Standard security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security`, `Content-Security-Policy`) are entirely absent.

All findings in this report are verified directly against the current repository source code.

---

## 2. Current Security Architecture

### 2.1 Perimeter & Middleware Stack
- **FastAPI Application Setup:** Located at `backend/app/main.py#L42-L66`.
- **Installed Middleware:** Only `CORSMiddleware` is configured.
  - Allowed origins default to wildcard `["*"]` in development, with `allow_credentials=False` (hardened in Phase 4.1 to comply with CORS specifications).
- **Missing Perimeter Controls:**
  - No Rate Limiting Middleware.
  - No Request Body Size Limiter / Streaming Ceiling.
  - No Security Headers Middleware (`HSTS`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`).
  - No Reverse Proxy / Trusted Host Middleware.

### 2.2 Storage & Identity Layer
- **Database Engine:** Async SQLAlchemy over SQLite (local/test) and PostgreSQL (production).
- **Connection Resiliency:** Pre-ping (`pool_pre_ping=True`) and connection recycling (`pool_recycle=1800`) are active.
- **Identity Schema:** The `User` model exists in the database schema (`users` table) with fields `id`, `email`, `password_hash`, `role`, and `is_anonymous`. Foreign key `identification_requests.user_id` exists in the schema.
- **Service Layer Status:** Zero authentication endpoints, password hashing utilities, or session verification dependencies exist.

---

## 3. Rate Limiting Assessment

### 3.1 Verification of Existing Implementation
- **Verified Code:** `backend/app/api/v1/identifications.py#L145-L216` and `backend/app/main.py`.
- **Finding:** Rate limiting is **completely absent**. Neither endpoint-level decorators nor global middleware are present.
- **Installed Packages:** `backend/pyproject.toml#L7-L19` confirms no rate limiting packages (e.g. `slowapi`, `redis`) are installed.

### 3.2 Abuse Vector & Resource Exhaustion Risks
1. **Third-Party API Quota Depletion:** Pl@ntNet charges or enforces strict quota thresholds (per-day and per-minute) on API keys. Unthrottled submissions can exhaust the project's botanical quota in minutes, failing all legitimate field identifications with HTTP 503/429.
2. **CPU & Image Decompression Bombing:** Each submission executes Pillow image verification, EXIF transposition, RGB/RGBA conversion, and JPEG compression (`validate_and_prepare`). Repeated requests with 10MB images force continuous CPU spikes.
3. **Database Write Saturation:** Each new submission writes to `identification_requests` and acquires a row lock.

### 3.3 Identification Keying Strategy (IP vs. Device vs. User)
- **Per-IP Limiting Limitation:** In Malawi, mobile data subscribers on cellular networks (Airtel Malawi, TNM) operate behind Carrier-Grade NAT (CGNAT). Hundreds or thousands of mobile devices share a small pool of public IP addresses. Aggressive IP-based throttling risks collateral blocking of legitimate users.
- **Per-User Limiting Limitation:** Users are not currently authenticated.
- **Recommended Keying Strategy:**
  - **Tier 1 (Client Identification):** Key by client-provided `X-Device-Id` (persistent client UUID generated by Flutter and stored in `SharedPreferences`) or `X-Client-Request-Id`.
  - **Tier 2 (IP Fallback & Safety Net):** Key by client IP address (`request.client.host` or sanitized `X-Forwarded-For` from trusted reverse proxies) with a significantly higher burst threshold to accommodate cellular NAT gateways.

### 3.4 In-Memory vs. Shared Storage Architecture
- **In-Memory Limiter (e.g., Token Bucket via dictionary or `slowapi` MemoryStorage):**
  - *Feasibility:* Low overhead, zero infrastructure dependencies, operates cleanly in local development.
  - *Limitation:* Does not synchronize state across multiple Uvicorn workers (`uvicorn --workers 4`) or multi-container containerized deployments. An attacker can bypass the limit by round-robining across worker processes.
- **Shared Storage (Redis):**
  - *Recommendation:* Provide an extensible rate-limiting interface that defaults to an in-memory sliding window for single-worker/dev environments, with a production Redis backend configurable via `settings.REDIS_URL`.

### 3.5 Offline-First Bursts & Recommendation
- **The Offline Ingestion Problem:** A field researcher without cellular connectivity in Nyika National Park or Mount Mulanje may record 5 to 10 plant observations offline. When the device returns to cellular range, the Flutter app flushes queued observations in rapid succession.
- **Recommended Algorithm:** **Token Bucket with Burst Allowance**.
  - *Proposed Values (Recommendation Only):*
    - **Identification Endpoint (`POST /api/v1/identifications`):**
      - Sustained Rate: 5 requests per minute.
      - Burst Allowance (Bucket Capacity): 15 requests (allows offline sync batching).
    - **Read-Only Catalogue (`GET /api/v1/plants`, `GET /api/v1/districts`):**
      - Sustained Rate: 60 requests per minute.
      - Burst Allowance: 120 requests.

---

## 4. Image Upload Security Assessment

### 4.1 Existing Protections (Verified in Code)
Located at `backend/app/identification/image_validation.py`:
1. **In-Memory Only:** Images are processed in `io.BytesIO` buffers. No files are written to the local host filesystem, eliminating directory traversal and local file inclusion (LFI) risks.
2. **Format Whitelisting by Content:** Formats are strictly checked via Pillow header parsing (`img.verify()`), allowing only `JPEG`, `PNG`, and `WEBP`. File extensions and user-controlled filenames are ignored.
3. **MIME/Content Consistency:** Rejects declared MIME types that conflict with actual byte signatures.
4. **Dimension Pre-Check:** Checks `width > 4096 or height > 4096` immediately after header decoding, before full pixel array decompression.
5. **EXIF Sanitization:** Strips all metadata (including GPS coordinates, camera serial numbers, and author comments) by decoding and re-encoding to a clean JPEG or PNG buffer.
6. **WebP Normalization:** Converts WebP to JPEG before handing off to the identification provider.

### 4.2 Identified Vulnerabilities & Missing Protections
1. **Unbounded Memory Buffering Before Size Guard:**
   - In `identifications.py#L198`:
     ```python
     raw_bytes = await image.read()
     ```
   - `image.read()` buffers the entire incoming stream into process RAM before `validate_and_prepare` enforces `len(raw_bytes) > settings.MAX_UPLOAD_SIZE_BYTES`.
   - *Risk:* An attacker sending a 100MB+ streaming multipart upload forces the Python runtime to allocate 100MB of RAM per connection, creating a Denial of Service (OOM) vector before any application validation runs.
2. **Lack of Explicit `UploadFile.close()` Cleanup:**
   - In `identifications.py#L198-L214`, `image.close()` is never called in a `finally` block. If `validate_and_prepare` or `run_identification` raises an exception, Starlette's `SpooledTemporaryFile` underlying descriptor remains open until finalizer garbage collection.
3. **Maximum Decompressed Memory (Pixel Dimension Ceiling):**
   - Max dimension is 4096 px per side. A 4096 × 4096 RGBA bitmap expands to ~67 MB of raw uncompressed pixel data in RAM.
   - For botanical identification (where mobile cameras focus on flowers and leaves), 2048 × 2048 px is more than adequate and caps decompressed bitmap RAM to ~16 MB (a 75% reduction).
4. **Missing Total Pixel Area Check:**
   - The code checks `width > max_dim or height > max_dim`, but does not enforce a maximum total pixel count (`width * height`).

---

## 5. Identification Endpoint Security (`POST /api/v1/identifications`)

### 5.1 Idempotency & Database Integrity (Existing Protections)
Located at `backend/app/identification/service.py#L498-L580`:
1. **Two-Phase Reservation:** A database row in `identification_requests` with `status="processing"` is committed *before* external inference starts.
2. **Payload Fingerprinting:** Computes SHA-256 of image bytes. If an identical `X-Client-Request-Id` is resubmitted with a different image, the service rejects it with `HTTP 409 Conflict`.
3. **Cached Response Return:** Completed requests return the persisted response immediately without re-invoking the provider.
4. **Lease Fencing:** If an active lease is running, concurrent requests receive `HTTP 503 Retryable`. Expired leases are reclaimed with an incremented `lease_version`. Stale workers that complete late cannot overwrite newer records.

### 5.2 Identified Weaknesses & Failure Modes
1. **Idempotency Bypass on Missing Header:**
   - Code: `effective_request_id = (client_request_id or "").strip() or str(uuid.uuid4())`.
   - If the client does not send `X-Client-Request-Id`, every single submission gets a new random UUID. Even if the user submits the exact same photo 10 times, 10 separate inference calls and database records are generated.
2. **Semantic Error Code Discrepancy on Header Validation:**
   - In `identifications.py#L187-L195`:
     ```python
     if len(client_req_id) > 64:
         raise HTTPException(
             status_code=status.HTTP_400_BAD_REQUEST,
             detail=IdentificationErrorResponse(
                 error_code=IdentificationErrorCode.IMAGE_DECODING_FAILED,
                 message="X-Client-Request-Id exceeds maximum allowed length of 64 characters.",
                 ...
             )
         )
     ```
   - Returning `IMAGE_DECODING_FAILED` for an invalid HTTP header length confuses client error-handling logic.
3. **Log Injection Exposure:**
   - In `identifications.py#L200-L206`: `image.filename` is logged directly without character sanitization. If a client sends a filename containing `\r\n`, log forgery is possible.

---

## 6. Authentication and Authorization Assessment

### 6.1 Current Status: Fail-Closed Vacuum
- Endpoints `GET /api/v1/identifications` and `GET /api/v1/identifications/{identification_id}` return `HTTP 503 Service Unavailable`:
  ```json
  {
    "detail": "Identification history is temporarily unavailable pending user authentication integration in Phase 4. Records are securely preserved and cannot be accessed anonymously."
  }
  ```
- **Security Assessment:** This fail-closed posture successfully prevents unauthorized enumeration and data leakage of past user discoveries.
- **Root Problem:** Neither the backend nor the Flutter frontend possesses an authentication subsystem.

### 6.2 Frontend Architecture Reality
- Inspection of Flutter source files (`lib/store.dart`, `lib/models.dart`) confirms:
  - FloraMW Flutter app stores history locally in `AppStore.history` via `SharedPreferences`.
  - The app contains **zero** HTTP authentication headers, token storage, login screens, or user account models.
- **Conflict:** Requiring an OAuth2/JWT username-and-password login on the backend would instantly break compatibility with the current Flutter application.

### 6.3 Safe Path Forward for Authentication & Authorization
1. **Anonymous Device Identity (Short-Term):**
   - Allow the client to generate and persist a cryptographically random `X-Device-Id` (UUID v4) on initial launch.
   - History queries can be scoped strictly to the requesting `X-Device-Id`:
     `WHERE identification_requests.client_request_id LIKE :device_prefix` or by mapping `X-Device-Id` to an anonymous row in `users` (`is_anonymous=True`).
2. **Optional User Accounts (Long-Term):**
   - Retain anonymous usage as the primary default.
   - When a user eventually creates an account (email/password), link the anonymous device history records to the registered `user_id`.

---

## 7. Offline-First Compatibility

Any security controls implemented in Phase 4.2 must accommodate FloraMW's core mission: field identification in Malawi where connectivity is intermittent or non-existent.

| Security Control | Threat Mitigated | Risk to Offline-First Client | Architectural Compatibility Solution |
|:---|:---|:---|:---|
| **Rate Limiting** | Quota exhaustion, DoS | Reconnection sync burst rejected with 429 | Use **Token Bucket with burst allowance** (e.g. allow up to 15 queued uploads upon reconnecting). |
| **Idempotency** | Duplicate processing on network timeouts | Duplicate submissions recorded on cellular drops | Client must generate `X-Client-Request-Id` at image capture time, persisting it locally until confirmed by the server. |
| **Authentication** | History enumeration | Login required before offline observation | Use **Device-UUID scoped access** or anonymous bearer tokens created without network dependencies. |
| **Request Size Ceiling** | Memory exhaustion | Legitimate high-res camera photos rejected | Set size limit to 10MB, but enforce stream ceiling before full memory buffering. |

---

## 8. Identified Risks and Severity Matrix

| ID | Finding / Vulnerability | Dimension | Impact | Severity |
|:---:|:---|:---|:---|:---:|
| **SEC-01** | **Unthrottled Identification Ingestion:** Zero rate limiting on `POST /api/v1/identifications`. | Availability / Cost | Pl@ntNet API quota depletion; worker CPU/RAM saturation. | **HIGH** |
| **SEC-02** | **Unbounded Memory Buffering on Upload:** `image.read()` reads stream before size limit check. | Availability | Memory exhaustion (OOM) via oversized multipart uploads. | **HIGH** |
| **SEC-03** | **Idempotency Key Bypass on Missing Header:** Omitting `X-Client-Request-Id` forces server-generated UUID. | Cost / Data Integrity | Redundant external API calls for duplicate image uploads. | **MEDIUM** |
| **SEC-04** | **Absence of Standard HTTP Security Headers:** No HSTS, X-Content-Type-Options, or CSP configured. | Transport / Defense | MIME-confusion attacks; clickjacking in web wrappers. | **MEDIUM** |
| **SEC-05** | **Identification History Blocked (Fail-Closed 503):** History inaccessible to client. | Integration | Remote history inaccessible; multi-device discovery blocked. | **MEDIUM** |
| **SEC-06** | **Semantic Error Code Discrepancy:** Header length validation returns `IMAGE_DECODING_FAILED`. | API Integrity | Client receives misleading error code on header validation. | **LOW** |
| **SEC-07** | **Unsanitized Filename Logging:** `image.filename` logged directly in request log. | Logging / Audit | Potential log injection via control characters (`\r\n`). | **LOW** |

---

## 9. Recommended Phase 4.2 Implementation Plan

Phase 4.2 should be executed as a focused, modular security hardening milestone divided into three sequential steps:

### Step 1: In-Flight Request Protection & Security Headers
1. **Streaming Upload Size Limiter:** Introduce a lightweight Starlette middleware or dependency that inspects `Content-Length` and enforces a streaming chunk ceiling on `POST /api/v1/identifications`, rejecting oversized uploads before buffering into memory.
2. **Explicit `UploadFile.close()`:** Wrap upload handling in `try...finally` to guarantee file descriptor cleanup.
3. **HTTP Security Headers Middleware:** Add standard security headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Strict-Transport-Security: max-age=31536000; includeSubDomains`).
4. **Filename Log Sanitization:** Sanitize `image.filename` before logging to eliminate CRLF characters.
5. **Header Error Code Alignment:** Correct line 191 of `identifications.py` to use `IdentificationErrorCode.PROVIDER_ERROR` or a validation code instead of `IMAGE_DECODING_FAILED`.

### Step 2: Rate Limiting Middleware with Burst Tolerance
1. **Modular Rate Limiter:** Implement a token-bucket rate limiter that evaluates `X-Device-Id` (or client IP if absent).
2. **Burst Tolerance Configuration:**
   - Configure defaults in `app/core/config.py`: `RATE_LIMIT_IDENTIFICATIONS_PER_MINUTE=5`, `RATE_LIMIT_IDENTIFICATIONS_BURST=15`.
3. **Standard HTTP 429 Response:** Return RFC 6585-compliant `429 Too Many Requests` with a standard `Retry-After` header and structured error response matching `IdentificationErrorResponse`.

### Step 3: Anonymous Device-Scoped History Access (Optional / Staged)
1. Maintain fail-closed posture for completely unauthenticated anonymous browser traffic.
2. Support `X-Device-Id` header to permit clients to retrieve identification history records created by that specific device without requiring a full user authentication flow.

---

## 10. Required Automated Tests

To maintain FloraMW's 254-test baseline, the following automated test suites must be developed in Phase 4.2:

### 10.1 Rate Limiting Tests (`tests/test_rate_limiting.py`)
- `test_identification_under_limit_succeeds`: Valid requests within burst limit return 200.
- `test_identification_exceeding_limit_returns_429`: Requests exceeding burst limit receive HTTP 429.
- `test_rate_limit_retry_after_header_present`: Confirms `Retry-After` header is included in 429 response.
- `test_rate_limit_keyed_by_device_id`: Verifies separate devices receive independent rate-limiting buckets.
- `test_rate_limit_burst_tolerance_accommodates_sync`: Confirms 10 rapid submissions succeed when burst allowance is configured to 15.

### 10.2 Upload Security Tests (`tests/test_upload_security.py`)
- `test_oversized_upload_aborted_before_memory_saturation`: Validates rejection of oversized streaming payloads.
- `test_corrupted_image_file_descriptor_closed`: Confirms `UploadFile.close()` is executed on decoding exceptions.
- `test_security_headers_present_on_all_responses`: Confirms `X-Content-Type-Options`, `X-Frame-Options`, and `HSTS` on API endpoints.
- `test_filename_with_crlf_sanitized_in_logs`: Validates log injection prevention.
- `test_header_length_exceeded_returns_appropriate_error_code`: Confirms corrected error code on oversized header.

---

## 11. Files Likely to Require Changes in a Future Implementation

1. `backend/app/main.py`: Register security headers middleware and rate-limiting middleware.
2. `backend/app/core/config.py`: Add rate-limiting parameters (`RATE_LIMIT_IDENTIFICATIONS_PER_MINUTE`, `RATE_LIMIT_BURST`).
3. `backend/app/api/v1/identifications.py`: Streaming size check, explicit `UploadFile.close()`, error code correction, filename sanitization.
4. `backend/app/core/rate_limit.py`: New module providing token-bucket / sliding-window rate-limiting logic.
5. `backend/tests/test_rate_limiting.py`: New test suite verifying rate limiting.
6. `backend/tests/test_upload_security.py`: New test suite verifying upload security and HTTP headers.

---

## 12. Outstanding Decisions and Dependencies

The following design decisions require approval before Phase 4.2 implementation begins:

1. **Rate Limiting Keying Decision:**
   - *Option A:* Key strictly by client IP address. (Simple, but risks throttling Malawian mobile users behind cellular CGNAT).
   - *Option B (Recommended):* Key primarily by `X-Device-Id` header (with fallback to client IP), pairing a generous burst capacity (15) with a steady refill rate (5/min).
2. **Rate Limiting Backend Storage:**
   - *Option A:* Pure in-memory dictionary with scheduled TTL cleanup. (Zero dependencies; optimal for current single-process SQLite/local development).
   - *Option B:* Pluggable limiter that defaults to in-memory, but supports Redis via `REDIS_URL` for production multi-worker deployments.
3. **History Endpoint Authorization Scope:**
   - *Option A:* Keep `GET /api/v1/identifications` fail-closed (HTTP 503) until the Flutter team builds a full user authentication flow.
   - *Option B:* Unlock device-scoped history via `X-Device-Id` so the Flutter app can retrieve past discoveries without user passwords.

---

## 13. Summary of Top Findings & Recommended Order of Implementation

### Most Important Findings
1. **Zero Rate Limiting:** The identification endpoint is fully exposed to abuse and quota exhaustion.
2. **In-Flight Memory Buffering:** Large uploads are read entirely into memory before size validation.
3. **Cellular CGNAT Sensitivity:** Rigid IP rate-limiting will disproportionately harm Malawian mobile users; a burst-tolerant token-bucket keyed by device ID is essential.
4. **Missing Security Headers:** Standard browser/HTTP security headers are not mounted.

### Recommended Order of Implementation
1. **Phase 4.2.1 — Upload & Transport Hardening:** Mount HTTP security headers, streaming upload ceiling, explicit `UploadFile.close()` cleanup, and error code/logging fixes.
2. **Phase 4.2.2 — Burst-Tolerant Rate Limiting:** Introduce pluggable token-bucket rate limiting on `POST /api/v1/identifications` configured for offline reconnection bursts.
3. **Phase 4.2.3 — Test Suite Expansion:** Implement automated tests verifying rate limits, security headers, and upload defenses against the 254-test baseline.

