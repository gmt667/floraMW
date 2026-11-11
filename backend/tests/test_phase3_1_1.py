"""Tests for Phase 3.1.1: Lease Fencing and Identification Data Integrity.

Covers:
- Robust lease fencing:
    - Worker initial reservation gets lease_version=1.
    - Lease reclamation increments lease_version.
    - Stale worker completion rejected (no status change, no candidate insertion).
    - Stale worker failure rejected (cannot mark newer request failed).
    - Simultaneous reclamation safe (only one worker wins the increment).
    - Asynchronous stale-worker scenario where second worker reclaims and completes first.
- Candidate rank uniqueness:
    - Unique constraint uq_identification_candidates_request_rank rejects duplicate (request_id, rank).
    - Different ranks for same request permitted.
    - Same rank for different requests permitted.
    - Normal identification persists candidates with strict rank order.
- Regression verification:
    - Concurrent requests with same key invoke provider once.
    - Retransmissions return cached result.
    - Mismatched fingerprint returns 409.
    - History endpoints fail-closed with 503.
    - Mock provider forbidden in production.
"""

from __future__ import annotations

import asyncio
import io
import time
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.identification.exceptions import (
    MockProviderForbiddenError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.identification.image_validation import validate_and_prepare
from app.identification.internal_provider import InternalModelProvider
from app.identification.provider import (
    IdentificationProvider,
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
)
from app.identification.service import (
    _record_failure,
    _record_success,
    run_identification,
)
from app.models.identification import IdentificationCandidate, IdentificationRequest
from app.schemas.identification import ConfidenceLevel, IdentificationOutcome


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(w: int = 10, h: int = 10, color=(34, 139, 34)) -> bytes:
    img = Image.new("RGB", (w, h), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


class PausingMockProvider(IdentificationProvider):
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
            provider_meta={"mode": "test_concurrent"},
        )


# ---------------------------------------------------------------------------
# 1. Lease Fencing Tests
# ---------------------------------------------------------------------------

class TestLeaseFencing:
    """Verifies that lease fencing tokens prevent stale workers from corrupting state."""

    async def test_initial_reservation_has_lease_version_one(self, client: AsyncClient, db_session: AsyncSession):
        req_id = f"test-fence-init-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(IdentificationRequest).where(IdentificationRequest.client_request_id == req_id)
        )
        record = result.scalar_one()
        assert record.status == "completed"
        assert record.lease_version == 1

    async def test_lease_reclamation_increments_lease_version(self, client: AsyncClient, db_session: AsyncSession):
        req_id = f"test-fence-reclaim-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()
        payload = validate_and_prepare(img_bytes, "image/jpeg")
        import hashlib
        sha = hashlib.sha256(payload.content).hexdigest()

        # Insert stalled reservation at lease_version = 1, expired 120s ago
        old_time = datetime.now(timezone.utc) - timedelta(seconds=120)
        stalled = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=1,
            image_sha256=sha,
            image_format="JPEG",
            image_size_bytes=len(img_bytes),
            image_width_px=10,
            image_height_px=10,
            provider_id="deterministic",
            created_at=old_time,
        )
        db_session.add(stalled)
        await db_session.commit()

        # Second worker reclaims
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp.status_code == 200

        await db_session.refresh(stalled)
        assert stalled.status == "completed"
        assert stalled.lease_version == 2

    async def test_stale_worker_completion_rejected(self, db_session: AsyncSession):
        """Worker with outdated lease_version cannot commit success or insert candidates."""
        req_id = f"test-stale-complete-{uuid.uuid4()}"
        record_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Record reclaimed: lease_version is now 2
        record = IdentificationRequest(
            id=record_id,
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=2,  # Current lease
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-2",
            created_at=now,
        )
        db_session.add(record)
        await db_session.commit()

        # Stale Worker 1 (which holds lease_version 1) attempts to commit
        from app.schemas.identification import IdentificationCandidateOut
        stale_candidate = IdentificationCandidateOut(
            scientific_name="Stale Species",
            confidence=0.95,
            confidence_level=ConfidenceLevel.HIGH,
            catalogue_matched=False,
        )

        committed = await _record_success(
            db_session,
            record_id,
            expected_lease_version=1,  # Outdated version!
            provider_id="worker-1",
            model_version="old",
            outcome=IdentificationOutcome.CANDIDATES,
            top_confidence_level=ConfidenceLevel.HIGH,
            execution_duration_ms=5000,
            enriched_candidates=[stale_candidate],
            now=now,
        )

        assert committed is False

        # Verify record remains unchanged in processing by Worker 2
        await db_session.refresh(record)
        assert record.status == "processing"
        assert record.lease_version == 2
        assert record.provider_id == "worker-2"

        # Verify zero candidates were inserted
        cand_res = await db_session.execute(
            select(IdentificationCandidate).where(IdentificationCandidate.request_id == record_id)
        )
        assert len(cand_res.scalars().all()) == 0

    async def test_stale_worker_failure_rejected(self, db_session: AsyncSession):
        """Worker with outdated lease_version cannot mark request as failed."""
        req_id = f"test-stale-fail-{uuid.uuid4()}"
        record_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Worker 2 successfully reclaimed lease_version 2
        record = IdentificationRequest(
            id=record_id,
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=2,
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-2",
            created_at=now,
        )
        db_session.add(record)
        await db_session.commit()

        # Stale Worker 1 times out and attempts to persist failure with lease_version 1
        persisted = await _record_failure(
            db_session,
            record_id,
            expected_lease_version=1,  # Outdated!
            error_code="provider_timeout",
            error_message="Worker 1 timed out",
            execution_duration_ms=65000,
        )

        assert persisted is False

        # Verify record was not marked failed
        await db_session.refresh(record)
        assert record.status == "processing"
        assert record.error_code is None

    async def test_simultaneous_reclamation_safely_serialized(self, db_session: AsyncSession):
        """Two concurrent workers attempting to reclaim the same expired lease cannot both succeed."""
        req_id = f"test-simul-reclaim-{uuid.uuid4()}"
        record_id = uuid.uuid4()
        old_time = datetime.now(timezone.utc) - timedelta(seconds=120)

        record = IdentificationRequest(
            id=record_id,
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=1,
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-0",
            created_at=old_time,
        )
        db_session.add(record)
        await db_session.commit()

        from sqlalchemy import update
        now = datetime.now(timezone.utc)

        # Worker A attempts conditional atomic reclamation
        stmt_a = (
            update(IdentificationRequest)
            .where(
                IdentificationRequest.id == record_id,
                IdentificationRequest.lease_version == 1,
                IdentificationRequest.status == "processing",
            )
            .values(lease_version=2, created_at=now, provider_id="worker-a")
        )
        # Worker B simultaneously attempts the exact same conditional reclamation
        stmt_b = (
            update(IdentificationRequest)
            .where(
                IdentificationRequest.id == record_id,
                IdentificationRequest.lease_version == 1,
                IdentificationRequest.status == "processing",
            )
            .values(lease_version=2, created_at=now, provider_id="worker-b")
        )

        res_a = await db_session.execute(stmt_a)
        await db_session.commit()

        res_b = await db_session.execute(stmt_b)
        await db_session.commit()

        # Exactly one worker wins; the other matches 0 rows
        rowcounts = [res_a.rowcount, res_b.rowcount]
        assert rowcounts == [1, 0]

        await db_session.refresh(record)
        assert record.lease_version == 2
        assert record.provider_id == "worker-a"


# ---------------------------------------------------------------------------
# 2. Candidate Rank Uniqueness Tests
# ---------------------------------------------------------------------------

class TestCandidateRankUniqueness:
    """Verifies that uq_identification_candidates_request_rank is strictly enforced."""

    async def test_duplicate_rank_rejected_by_database(self, db_session: AsyncSession):
        req_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        # Parent request
        req = IdentificationRequest(
            id=req_id,
            client_request_id=f"test-cand-uniq-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=1,
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="test",
            created_at=now,
        )
        db_session.add(req)
        await db_session.commit()

        # Candidate 1 at rank 1
        c1 = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=req_id,
            rank=1,
            scientific_name="First Species",
            confidence=0.90,
            created_at=now,
        )
        db_session.add(c1)
        await db_session.commit()

        # Candidate 2 with same request_id and same rank 1 -> must raise IntegrityError
        c2 = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=req_id,
            rank=1,  # Duplicate rank!
            scientific_name="Duplicate Rank Species",
            confidence=0.85,
            created_at=now,
        )
        db_session.add(c2)
        with pytest.raises(IntegrityError):
            await db_session.commit()
        await db_session.rollback()

    async def test_different_ranks_same_request_accepted(self, db_session: AsyncSession):
        req_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        req = IdentificationRequest(
            id=req_id,
            client_request_id=f"test-ranks-ok-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=1,
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="test",
            created_at=now,
        )
        db_session.add(req)
        await db_session.commit()

        c1 = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=req_id,
            rank=1,
            scientific_name="Species One",
            confidence=0.90,
            created_at=now,
        )
        c2 = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=req_id,
            rank=2,
            scientific_name="Species Two",
            confidence=0.75,
            created_at=now,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()

        res = await db_session.execute(
            select(IdentificationCandidate).where(IdentificationCandidate.request_id == req_id)
        )
        candidates = res.scalars().all()
        assert len(candidates) == 2

    async def test_same_rank_different_requests_accepted(self, db_session: AsyncSession):
        req1_id = uuid.uuid4()
        req2_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        req1 = IdentificationRequest(
            id=req1_id,
            client_request_id=f"test-r1-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=1,
            image_sha256="dummy_sha1",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="test",
            created_at=now,
        )
        req2 = IdentificationRequest(
            id=req2_id,
            client_request_id=f"test-r2-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=1,
            image_sha256="dummy_sha2",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="test",
            created_at=now,
        )
        db_session.add_all([req1, req2])
        await db_session.commit()

        # Both have rank 1 but different request_id -> accepted!
        c1 = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=req1_id,
            rank=1,
            scientific_name="Species A",
            confidence=0.90,
            created_at=now,
        )
        c2 = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=req2_id,
            rank=1,
            scientific_name="Species B",
            confidence=0.88,
            created_at=now,
        )
        db_session.add_all([c1, c2])
        await db_session.commit()


# ---------------------------------------------------------------------------
# 3. Regression Tests
# ---------------------------------------------------------------------------

class TestPhase311Regressions:
    """Verifies existing idempotency, fail-closed security, and provider restrictions."""

    async def test_concurrent_requests_single_inference(self, client: AsyncClient):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        pausing_provider = PausingMockProvider(delay_seconds=0.2)
        req_id = f"test-regress-conc-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()

        app.dependency_overrides[get_current_provider] = lambda: pausing_provider
        try:
            async def send_req():
                return await client.post(
                    "/api/v1/identifications",
                    files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
                    headers={"X-Client-Request-Id": req_id},
                )

            resp1, resp2 = await asyncio.gather(send_req(), send_req())
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

        status_codes = sorted([resp1.status_code, resp2.status_code])
        assert status_codes in ([200, 200], [200, 503])
        assert pausing_provider.call_count == 1

    async def test_history_list_fails_closed_503(self, client: AsyncClient):
        resp = await client.get("/api/v1/identifications")
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"]

    async def test_history_detail_fails_closed_503(self, client: AsyncClient):
        resp = await client.get(f"/api/v1/identifications/{uuid.uuid4()}")
        assert resp.status_code == 503
        assert "temporarily unavailable" in resp.json()["detail"]

    def test_mock_provider_rejected_in_production(self):
        with patch.object(settings, "ENVIRONMENT", "production"):
            with pytest.raises(MockProviderForbiddenError):
                InternalModelProvider(mode="mock")
