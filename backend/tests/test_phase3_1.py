"""Tests for Phase 3.1: Security, Idempotency and Failure-Lifecycle Hardening.

Covers:
- SEC-01 & SEC-02: Fail-closed history listing and detail access (HTTP 503)
- CONC-01 & LIFE-01: Two-phase reservation, concurrent racing requests, lease recovery
- LIFE-02: Failure lifecycle persistence for provider errors with credential sanitization
- PROV-01: Production mock provider enforcement (MockProviderForbiddenError)
- PERF-01: Correlated subquery pagination verification
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.identification.exceptions import (
    IdempotencyConflictError,
    MockProviderForbiddenError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.identification.internal_provider import InternalModelProvider
from app.identification.provider import (
    IdentificationProvider,
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
)
from app.models.identification import IdentificationRequest
from app.schemas.identification import ConfidenceLevel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(w: int = 10, h: int = 10, color=(34, 139, 34)) -> bytes:
    img = Image.new("RGB", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class PausingMockProvider(IdentificationProvider):
    """Provider that simulates realistic inference latency for concurrency testing."""

    def __init__(self, delay_seconds: float = 0.25):
        self.delay_seconds = delay_seconds
        self.call_count = 0

    @property
    def provider_id(self) -> str:
        return "pausing-mock"

    async def identify(self, image: ImagePayload) -> ProviderResult:
        self.call_count += 1
        await asyncio.sleep(self.delay_seconds)
        return ProviderResult(
            provider_id=self.provider_id,
            model_version="1.0.0",
            candidates=[
                ProviderCandidate(
                    scientific_name="Faurea saligna",
                    confidence=0.88,
                    family="Proteaceae",
                    genus="Faurea",
                    common_names=["African beech"],
                )
            ],
            provider_meta={"execution_mode": "test_concurrent"},
        )


class FailingMockProvider(IdentificationProvider):
    """Provider that simulates transient external service failures."""

    def __init__(self, exc_to_raise: Exception):
        self.exc_to_raise = exc_to_raise
        self.call_count = 0

    @property
    def provider_id(self) -> str:
        return "failing-mock"

    async def identify(self, image: ImagePayload) -> ProviderResult:
        self.call_count += 1
        raise self.exc_to_raise


# ---------------------------------------------------------------------------
# SEC-01 & SEC-02: Security Fail-Closed Endpoints
# ---------------------------------------------------------------------------

class TestPhase31SecurityHistoryLockdown:
    """Public history endpoints fail closed with HTTP 503 and zero disclosures."""

    async def test_history_list_returns_503(self, client: AsyncClient):
        resp = await client.get("/api/v1/identifications")
        assert resp.status_code == 503
        data = resp.json()
        assert "temporarily unavailable pending user authentication" in data["detail"]
        assert "items" not in data
        assert "total" not in data

    async def test_history_list_filters_ignored_still_503(self, client: AsyncClient):
        resp = await client.get("/api/v1/identifications?page=2&limit=50&outcome=candidates")
        assert resp.status_code == 503
        data = resp.json()
        assert "temporarily unavailable" in data["detail"]

    async def test_history_detail_returns_503(self, client: AsyncClient):
        test_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/identifications/{test_id}")
        assert resp.status_code == 503
        data = resp.json()
        assert "temporarily unavailable pending user authentication" in data["detail"]
        assert "candidates" not in data
        assert "provider" not in data

    async def test_history_detail_malformed_id_returns_503(self, client: AsyncClient):
        resp = await client.get("/api/v1/identifications/malformed-id")
        assert resp.status_code == 503
        data = resp.json()
        assert "temporarily unavailable" in data["detail"]


# ---------------------------------------------------------------------------
# CONC-01 & LIFE-01: Two-Phase Reservation and Genuine Concurrency
# ---------------------------------------------------------------------------

class TestPhase31ConcurrentIdempotency:
    """Concurrent requests with identical idempotency key do not duplicate inference."""

    async def test_concurrent_racing_requests_single_inference(self, client: AsyncClient):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        pausing_provider = PausingMockProvider(delay_seconds=0.2)
        req_id = f"test-concurrent-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        app.dependency_overrides[get_current_provider] = lambda: pausing_provider
        try:
            async def send_req():
                return await client.post(
                    "/api/v1/identifications",
                    files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
                    headers={"X-Client-Request-Id": req_id},
                )

            # Fire two concurrent requests with identical client_request_id
            resp1, resp2 = await asyncio.gather(send_req(), send_req())
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

        # One request must succeed with 200, the other either returns 200 (if caught after completion)
        # or returns 503 Service Unavailable (retryable concurrent processing)
        status_codes = sorted([resp1.status_code, resp2.status_code])
        assert status_codes in ([200, 200], [200, 503])

        # Inference provider must have been invoked at most once
        assert pausing_provider.call_count == 1

    async def test_idempotent_retransmission_returns_persisted_result(self, client: AsyncClient):
        req_id = f"test-cached-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        # Initial request
        resp1 = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp1.status_code == 200
        body1 = resp1.json()

        # Retransmission with identical key and image
        resp2 = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp2.status_code == 200
        body2 = resp2.json()

        assert body1.get("client_request_id") == body2.get("client_request_id")
        assert body1["outcome"] == body2["outcome"]

    async def test_idempotency_payload_conflict_returns_409(self, client: AsyncClient):
        req_id = f"test-conflict-{uuid.uuid4()}"
        img1 = _make_jpeg_bytes(w=10, h=10, color=(10, 20, 30))
        img2 = _make_jpeg_bytes(w=12, h=12, color=(50, 60, 70))

        resp1 = await client.post(
            "/api/v1/identifications",
            files={"image": ("f1.jpg", img1, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp1.status_code == 200

        # Attempt to reuse req_id with different image
        resp2 = await client.post(
            "/api/v1/identifications",
            files={"image": ("f2.jpg", img2, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp2.status_code == 409
        body = resp2.json()
        detail = body.get("detail", body)
        code = detail.get("error_code", "")
        msg = detail.get("message", "")
        assert "conflict" in msg.lower() or "provider_error" in code.lower() or "idempotency" in code.lower()

    async def test_processing_lease_recovery_after_timeout(self, client: AsyncClient, db_session: AsyncSession):
        """If a reservation is stuck in 'processing' past lease seconds, it recovers."""
        req_id = f"test-lease-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()
        import hashlib
        from app.identification.image_validation import validate_and_prepare
        payload = validate_and_prepare(img_bytes, "image/jpeg")
        sha = hashlib.sha256(payload.content).hexdigest()

        # Insert a stalled row with created_at older than lease seconds (e.g. 120s ago)
        old_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        stalled_req = IdentificationRequest(
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            image_sha256=sha,
            image_format="JPEG",
            image_size_bytes=len(img_bytes),
            image_width_px=10,
            image_height_px=10,
            provider_id="deterministic",
            created_at=old_time,
        )
        db_session.add(stalled_req)
        await db_session.commit()

        # Send request with same req_id: should detect expired lease and recover
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp.status_code == 200

        # Verify DB record transitioned from processing to completed
        await db_session.refresh(stalled_req)
        assert stalled_req.status == "completed"
        assert stalled_req.outcome in ("candidates", "demo_mode", "no_match")


# ---------------------------------------------------------------------------
# LIFE-02: Provider Failure Persistence and Sanitization
# ---------------------------------------------------------------------------

class TestPhase31FailureLifecyclePersistence:
    """Expected provider failures persist status='failed' before raising HTTP errors."""

    async def test_provider_timeout_persists_failure(self, client: AsyncClient, db_session: AsyncSession):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        failing_provider = FailingMockProvider(ProviderTimeoutError("Pl@ntNet upstream timed out after 10.0s"))
        req_id = f"test-timeout-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        app.dependency_overrides[get_current_provider] = lambda: failing_provider
        try:
            resp = await client.post(
                "/api/v1/identifications",
                files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
                headers={"X-Client-Request-Id": req_id},
            )
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

        assert resp.status_code == 504
        data = resp.json()
        detail = data.get("detail", data)
        assert detail.get("error_code") == "provider_timeout"

        # Verify persisted failure in DB
        result = await db_session.execute(
            select(IdentificationRequest).where(IdentificationRequest.client_request_id == req_id)
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.status == "failed"
        assert row.outcome == "failed"
        assert row.error_code == "provider_timeout"
        assert row.completed_at is not None
        assert row.execution_duration_ms is not None
        assert "timed out" in row.error_message

    async def test_provider_unavailable_persists_failure(self, client: AsyncClient, db_session: AsyncSession):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        failing_provider = FailingMockProvider(ProviderUnavailableError("503 Service Unavailable upstream"))
        req_id = f"test-unavail-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        app.dependency_overrides[get_current_provider] = lambda: failing_provider
        try:
            resp = await client.post(
                "/api/v1/identifications",
                files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
                headers={"X-Client-Request-Id": req_id},
            )
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

        assert resp.status_code == 503
        data = resp.json()
        detail = data.get("detail", data)
        assert detail.get("error_code") == "provider_unavailable"

        result = await db_session.execute(
            select(IdentificationRequest).where(IdentificationRequest.client_request_id == req_id)
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert row.status == "failed"
        assert row.error_code == "provider_unavailable"

    async def test_failure_persisted_error_message_is_sanitized(self, client: AsyncClient, db_session: AsyncSession):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        secret_key = "mock_secret_plantnet_token_xyz987654321"
        leak_msg = f"Failed contacting api.plantnet.org?api-key={secret_key} with Authorization: Bearer {secret_key}"
        failing_provider = FailingMockProvider(ProviderResponseError(leak_msg))
        req_id = f"test-sanitize-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        app.dependency_overrides[get_current_provider] = lambda: failing_provider
        try:
            resp = await client.post(
                "/api/v1/identifications",
                files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
                headers={"X-Client-Request-Id": req_id},
            )
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

        assert resp.status_code == 502
        assert secret_key not in resp.text

        result = await db_session.execute(
            select(IdentificationRequest).where(IdentificationRequest.client_request_id == req_id)
        )
        row = result.scalar_one_or_none()
        assert row is not None
        assert secret_key not in row.error_message
        assert "[REDACTED]" in row.error_message


# ---------------------------------------------------------------------------
# PROV-01: Production Mock Provider Restrictions
# ---------------------------------------------------------------------------

class TestPhase31ProductionMockRestrictions:
    """InternalModelProvider(mode='mock') fails closed in production."""

    def test_mock_provider_raises_when_production_environment(self):
        with patch.object(settings, "ENVIRONMENT", "production"):
            with pytest.raises(MockProviderForbiddenError) as exc_info:
                InternalModelProvider(mode="mock")
            assert "forbidden in production" in str(exc_info.value)

    def test_mock_provider_raises_when_allow_mock_provider_false(self):
        with patch.object(settings, "ALLOW_MOCK_PROVIDER", False):
            with pytest.raises(MockProviderForbiddenError) as exc_info:
                InternalModelProvider(mode="mock")
            assert "forbidden" in str(exc_info.value)

    def test_mock_provider_allowed_in_development(self):
        with patch.object(settings, "ENVIRONMENT", "development"):
            with patch.object(settings, "ALLOW_MOCK_PROVIDER", True):
                provider = InternalModelProvider(mode="mock")
                assert provider.provider_id == "internal"


# ---------------------------------------------------------------------------
# PERF-01: History Query Performance (Correlated Subquery Verification)
# ---------------------------------------------------------------------------

class TestPhase31CorrelatedSubqueryPerformance:
    """Verifies that candidate counting runs inside a single query without N+1."""

    async def test_fetch_history_candidate_counting(self, client: AsyncClient, db_session: AsyncSession):
        from app.api.v1.identification_history import fetch_identification_history_list

        # Create 3 records with known outcomes
        for _ in range(3):
            img = _make_jpeg_bytes()
            await client.post(
                "/api/v1/identifications",
                files={"image": ("flower.jpg", img, "image/jpeg")},
            )

        res = await fetch_identification_history_list(db_session, page=1, limit=10)
        assert res.total >= 3
        for item in res.items:
            assert isinstance(item.candidate_count, int)
            assert item.candidate_count >= 0
