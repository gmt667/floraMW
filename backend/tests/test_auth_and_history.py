"""Phase 4.3.2 — Secure Anonymous Identity and History Test Suite.

Exhaustive tests covering:
1. Anonymous identity issuance (POST /api/v1/auth/anonymous)
2. Token generation, hashing, and storage security (raw token never stored)
3. Authentication dependencies (get_current_user, get_optional_current_user)
4. Authenticated vs unauthenticated plant identification submissions
5. Protected identification history listing and strict user ownership filtering
6. Identification detail retrieval, candidate inclusion, and anti-IDOR protections (404 instead of 403)
7. Exclusion of legacy unowned records (user_id IS NULL) from history
8. Cross-user idempotency key collision isolation (HTTP 409)
9. Replay of idempotent requests by original owner (HTTP 200)
10. Rate limiting on anonymous identity creation (HTTP 429 after burst)
"""

from __future__ import annotations

import hashlib
import io
import uuid
from typing import Dict, Tuple

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select

from app.core.rate_limit import RateLimiter, set_rate_limiter
from app.core.rate_limit.storage import InMemoryRateLimitStorage
from app.models.identification import IdentificationRequest
from app.models.user import User
from app.schemas.identification import IdentificationErrorCode


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------


def _make_test_jpeg(width: int = 100, height: int = 80, color: Tuple[int, int, int] = (34, 139, 34)) -> bytes:
    """Generate an in-memory valid JPEG."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


TINY_JPEG = _make_test_jpeg()
ALT_JPEG = _make_test_jpeg(color=(200, 50, 50))


async def _create_test_identity(client: AsyncClient) -> Dict[str, str]:
    """Helper to register an anonymous user and return dict with user_id and device_token."""
    resp = await client.post("/api/v1/auth/anonymous")
    assert resp.status_code == 201
    data = resp.json()
    return {
        "user_id": data["user_id"],
        "device_token": data["device_token"],
        "auth_header": f"Bearer {data['device_token']}",
    }


# ===========================================================================
# 1. Anonymous Identity Issuance
# ===========================================================================


class TestAnonymousIdentityCreation:
    """Tests for POST /api/v1/auth/anonymous."""

    @pytest.mark.asyncio
    async def test_issue_anonymous_identity_success(self, client: AsyncClient):
        """Issuing an anonymous identity returns 201 with expected payload schema."""
        resp = await client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201
        data = resp.json()

        assert "user_id" in data
        assert uuid.UUID(data["user_id"])  # must be a valid UUID
        assert "device_token" in data
        assert len(data["device_token"]) == 64  # 32 bytes hex = 64 chars
        assert data["token_type"] == "bearer"
        assert data["role"] == "guest"
        assert data["is_anonymous"] is True
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_tokens_are_cryptographically_unique(self, client: AsyncClient):
        """Successive requests generate unique tokens and distinct user records."""
        resp1 = await client.post("/api/v1/auth/anonymous")
        resp2 = await client.post("/api/v1/auth/anonymous")

        data1 = resp1.json()
        data2 = resp2.json()

        assert data1["user_id"] != data2["user_id"]
        assert data1["device_token"] != data2["device_token"]

    @pytest.mark.asyncio
    async def test_raw_token_never_stored_in_database(self, client: AsyncClient, db_session):
        """Database stores only the SHA-256 hash of the token, never the raw token."""
        resp = await client.post("/api/v1/auth/anonymous")
        assert resp.status_code == 201
        data = resp.json()

        raw_token = data["device_token"]
        expected_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        user_uuid = uuid.UUID(data["user_id"])

        stmt = select(User).where(User.id == user_uuid)
        result = await db_session.execute(stmt)
        user = result.scalar_one_or_none()

        assert user is not None
        assert user.device_token_hash == expected_hash
        assert user.device_token_hash != raw_token
        # Ensure raw token does not match any User attribute
        assert user.role == "guest"
        assert user.is_anonymous is True


# ===========================================================================
# 2. Authentication Dependencies & Enforcement
# ===========================================================================


class TestAuthenticationEnforcement:
    """Tests for authentication checks on protected history endpoints."""

    @pytest.mark.asyncio
    async def test_history_list_missing_auth_returns_401(self, client: AsyncClient):
        """GET /api/v1/identifications without auth returns 401 with structured error."""
        resp = await client.get("/api/v1/identifications")
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.AUTHENTICATION_REQUIRED
        assert detail["retryable"] is False

    @pytest.mark.asyncio
    async def test_history_detail_missing_auth_returns_401(self, client: AsyncClient):
        """GET /api/v1/identifications/{id} without auth returns 401."""
        test_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/identifications/{test_id}")
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.AUTHENTICATION_REQUIRED

    @pytest.mark.asyncio
    async def test_invalid_bearer_token_returns_401(self, client: AsyncClient):
        """Supplying an unrecognized device token returns 401."""
        bogus_token = "f" * 64
        resp = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": f"Bearer {bogus_token}"},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.AUTHENTICATION_FAILED

    @pytest.mark.asyncio
    async def test_malformed_auth_header_returns_401(self, client: AsyncClient):
        """Supplying non-Bearer scheme or empty token returns 401."""
        # Non-Bearer scheme
        resp = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.AUTHENTICATION_FAILED

        # Bare Bearer with no token
        resp2 = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": "Bearer"},
        )
        assert resp2.status_code == 401
        assert resp2.json()["detail"]["error_code"] == IdentificationErrorCode.AUTHENTICATION_FAILED


# ===========================================================================
# 3. Identification Submission Ownership
# ===========================================================================


class TestIdentificationSubmissionOwnership:
    """Verify user ownership association during plant identification submissions."""

    @pytest.mark.asyncio
    async def test_unauthenticated_submission_leaves_user_id_null(
        self, client: AsyncClient, db_session
    ):
        """Anonymous submission without Bearer token results in user_id=None."""
        req_id = f"test-anon-sub-{uuid.uuid4()}"
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", TINY_JPEG, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp.status_code == 200

        stmt = select(IdentificationRequest).where(
            IdentificationRequest.client_request_id == req_id
        )
        result = await db_session.execute(stmt)
        record = result.scalar_one()
        assert record.user_id is None

    @pytest.mark.asyncio
    async def test_authenticated_submission_associates_user_id(
        self, client: AsyncClient, db_session
    ):
        """Submission with valid Bearer token associates record with caller's user_id."""
        user = await _create_test_identity(client)
        req_id = f"test-auth-sub-{uuid.uuid4()}"

        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user["auth_header"],
                "X-Client-Request-Id": req_id,
            },
        )
        assert resp.status_code == 200

        stmt = select(IdentificationRequest).where(
            IdentificationRequest.client_request_id == req_id
        )
        result = await db_session.execute(stmt)
        record = result.scalar_one()
        assert str(record.user_id) == user["user_id"]


# ===========================================================================
# 4. Identification History Listing & Scoping
# ===========================================================================


class TestIdentificationHistoryListing:
    """Verify user-scoped identification history listing."""

    @pytest.mark.asyncio
    async def test_history_list_filters_by_current_user(self, client: AsyncClient):
        """User A sees only User A's records; User B sees only User B's records."""
        user_a = await _create_test_identity(client)
        user_b = await _create_test_identity(client)

        # User A makes 2 submissions
        for i in range(2):
            resp = await client.post(
                "/api/v1/identifications",
                files={"image": (f"a_{i}.jpg", TINY_JPEG, "image/jpeg")},
                headers={
                    "Authorization": user_a["auth_header"],
                    "X-Client-Request-Id": f"user-a-req-{i}-{uuid.uuid4()}",
                },
            )
            assert resp.status_code == 200

        # User B makes 1 submission
        resp_b = await client.post(
            "/api/v1/identifications",
            files={"image": ("b_0.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user_b["auth_header"],
                "X-Client-Request-Id": f"user-b-req-0-{uuid.uuid4()}",
            },
        )
        assert resp_b.status_code == 200

        # Query User A history
        list_a = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": user_a["auth_header"]},
        )
        assert list_a.status_code == 200
        data_a = list_a.json()
        assert data_a["total"] == 2
        assert len(data_a["items"]) == 2

        # Query User B history
        list_b = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": user_b["auth_header"]},
        )
        assert list_b.status_code == 200
        data_b = list_b.json()
        assert data_b["total"] == 1
        assert len(data_b["items"]) == 1

    @pytest.mark.asyncio
    async def test_history_list_never_leaks_legacy_unowned_records(
        self, client: AsyncClient
    ):
        """Legacy records with user_id=None are strictly excluded from history lists."""
        user = await _create_test_identity(client)

        # Create unauthenticated submission (user_id IS NULL)
        resp_anon = await client.post(
            "/api/v1/identifications",
            files={"image": ("anon.jpg", TINY_JPEG, "image/jpeg")},
            headers={"X-Client-Request-Id": f"anon-req-{uuid.uuid4()}"},
        )
        assert resp_anon.status_code == 200

        # Check authenticated user's history
        history_resp = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": user["auth_header"]},
        )
        assert history_resp.status_code == 200
        data = history_resp.json()
        assert data["total"] == 0
        assert len(data["items"]) == 0

    @pytest.mark.asyncio
    async def test_history_pagination_and_query_filters(self, client: AsyncClient):
        """Verify page and limit pagination parameters."""
        user = await _create_test_identity(client)

        # Create 3 submissions
        for i in range(3):
            await client.post(
                "/api/v1/identifications",
                files={"image": (f"item_{i}.jpg", TINY_JPEG, "image/jpeg")},
                headers={
                    "Authorization": user["auth_header"],
                    "X-Client-Request-Id": f"page-req-{i}-{uuid.uuid4()}",
                },
            )

        # Request page 1 with limit 2
        resp = await client.get(
            "/api/v1/identifications?page=1&limit=2",
            headers={"Authorization": user["auth_header"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["page"] == 1
        assert data["limit"] == 2
        assert len(data["items"]) == 2

        # Request page 2 with limit 2
        resp_p2 = await client.get(
            "/api/v1/identifications?page=2&limit=2",
            headers={"Authorization": user["auth_header"]},
        )
        assert resp_p2.status_code == 200
        data_p2 = resp_p2.json()
        assert data_p2["total"] == 3
        assert data_p2["page"] == 2
        assert len(data_p2["items"]) == 1


# ===========================================================================
# 5. History Detail & Anti-IDOR Protections
# ===========================================================================


class TestIdentificationHistoryDetailAntiIDOR:
    """Verify history detail retrieval, candidate details, and anti-IDOR defenses."""

    @pytest.mark.asyncio
    async def test_owner_can_fetch_full_detail_and_candidates(self, client: AsyncClient):
        """Owning user can retrieve their complete identification record with candidates."""
        user = await _create_test_identity(client)
        req_id = f"detail-test-{uuid.uuid4()}"

        sub_resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user["auth_header"],
                "X-Client-Request-Id": req_id,
            },
        )
        assert sub_resp.status_code == 200

        # Retrieve record ID via list
        list_resp = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": user["auth_header"]},
        )
        record_id = list_resp.json()["items"][0]["id"]

        # Fetch detail
        detail_resp = await client.get(
            f"/api/v1/identifications/{record_id}",
            headers={"Authorization": user["auth_header"]},
        )
        assert detail_resp.status_code == 200
        data = detail_resp.json()
        assert data["id"] == record_id
        assert data["client_request_id"] == req_id
        assert len(data["candidates"]) > 0
        assert "rank" in data["candidates"][0]
        assert "scientific_name" in data["candidates"][0]

    @pytest.mark.asyncio
    async def test_anti_idor_cross_user_access_returns_404(self, client: AsyncClient):
        """User B querying User A's identification ID receives 404, not 403 (no ID leakage)."""
        user_a = await _create_test_identity(client)
        user_b = await _create_test_identity(client)

        await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user_a["auth_header"],
                "X-Client-Request-Id": f"idor-target-{uuid.uuid4()}",
            },
        )

        list_a = await client.get(
            "/api/v1/identifications",
            headers={"Authorization": user_a["auth_header"]},
        )
        record_id_a = list_a.json()["items"][0]["id"]

        # User B attempts to access User A's record
        cross_resp = await client.get(
            f"/api/v1/identifications/{record_id_a}",
            headers={"Authorization": user_b["auth_header"]},
        )
        assert cross_resp.status_code == 404
        assert "not found" in cross_resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_legacy_unowned_record_returns_404(
        self, client: AsyncClient, db_session
    ):
        """Legacy unowned record (user_id IS NULL) returns 404 to authenticated callers."""
        user = await _create_test_identity(client)
        req_id = f"anon-for-detail-{uuid.uuid4()}"

        await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", TINY_JPEG, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )

        stmt = select(IdentificationRequest.id).where(
            IdentificationRequest.client_request_id == req_id
        )
        result = await db_session.execute(stmt)
        anon_db_id = str(result.scalar_one())

        # Authenticated user tries to access unowned record
        resp = await client.get(
            f"/api/v1/identifications/{anon_db_id}",
            headers={"Authorization": user["auth_header"]},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_nonexistent_identification_id_returns_404(self, client: AsyncClient):
        """Random nonexistent UUID returns 404."""
        user = await _create_test_identity(client)
        random_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/identifications/{random_id}",
            headers={"Authorization": user["auth_header"]},
        )
        assert resp.status_code == 404


# ===========================================================================
# 6. Idempotency Key Cross-User Isolation & Replay
# ===========================================================================


class TestIdempotencyCrossUserIsolation:
    """Verify idempotency key ownership scoping."""

    @pytest.mark.asyncio
    async def test_cross_user_idempotency_key_collision_returns_409(
        self, client: AsyncClient
    ):
        """User B reusing User A's X-Client-Request-Id receives HTTP 409 Conflict."""
        user_a = await _create_test_identity(client)
        user_b = await _create_test_identity(client)
        shared_client_id = f"shared-idemp-{uuid.uuid4()}"

        # User A makes original submission
        resp_a = await client.post(
            "/api/v1/identifications",
            files={"image": ("img.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user_a["auth_header"],
                "X-Client-Request-Id": shared_client_id,
            },
        )
        assert resp_a.status_code == 200

        # User B submits using User A's client_request_id
        resp_b = await client.post(
            "/api/v1/identifications",
            files={"image": ("img.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user_b["auth_header"],
                "X-Client-Request-Id": shared_client_id,
            },
        )
        assert resp_b.status_code == 409
        detail = resp_b.json()["detail"]
        assert "used by another account" in detail["message"]

    @pytest.mark.asyncio
    async def test_same_user_idempotency_replay_succeeds(self, client: AsyncClient):
        """Original owner replaying request with same image receives cached 200 result."""
        user = await _create_test_identity(client)
        client_id = f"replay-idemp-{uuid.uuid4()}"

        # Initial request
        resp1 = await client.post(
            "/api/v1/identifications",
            files={"image": ("img.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user["auth_header"],
                "X-Client-Request-Id": client_id,
            },
        )
        assert resp1.status_code == 200
        data1 = resp1.json()

        # Replay request
        resp2 = await client.post(
            "/api/v1/identifications",
            files={"image": ("img.jpg", TINY_JPEG, "image/jpeg")},
            headers={
                "Authorization": user["auth_header"],
                "X-Client-Request-Id": client_id,
            },
        )
        assert resp2.status_code == 200
        data2 = resp2.json()

        assert data1["outcome"] == data2["outcome"]
        assert data1["client_request_id"] == data2["client_request_id"]
        assert len(data1["candidates"]) == len(data2["candidates"])


# ===========================================================================
# 7. Rate Limiting on Anonymous Identity Creation
# ===========================================================================


class TestAuthRateLimiting:
    """Verify rate limiting on POST /api/v1/auth/anonymous."""

    @pytest.mark.asyncio
    async def test_anonymous_auth_rate_limiting_burst_exhaustion(self, client: AsyncClient):
        """Exhausting the auth burst allowance triggers HTTP 429 Too Many Requests."""
        # Install a rate limiter with small burst for this test
        storage = InMemoryRateLimitStorage()
        test_limiter = RateLimiter(
            storage=storage,
            enabled=True,
            auth_per_minute=2.0,
            auth_burst=3,  # burst of 3
            global_enabled=False,
        )
        set_rate_limiter(test_limiter)

        headers = {"X-Forwarded-For": "198.51.100.42"}

        # First 3 requests must succeed (within burst)
        for i in range(3):
            resp = await client.post("/api/v1/auth/anonymous", headers=headers)
            assert resp.status_code == 201, f"Request {i+1} failed with {resp.status_code}"

        # 4th request must be rejected with 429
        resp_blocked = await client.post("/api/v1/auth/anonymous", headers=headers)
        assert resp_blocked.status_code == 429
        assert "Retry-After" in resp_blocked.headers
        detail = resp_blocked.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.RATE_LIMIT_EXCEEDED
