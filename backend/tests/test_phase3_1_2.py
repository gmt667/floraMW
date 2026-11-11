"""Tests for Phase 3.1.2: Identification Timestamp Integrity.

Covers:
- Timestamp immutability:
    - Initial reservation initializes both created_at and lease_assigned_at.
    - Lease reclamation advances lease_assigned_at while created_at remains strictly immutable.
    - Failed-request retries advance lease_assigned_at while created_at remains strictly immutable.
    - Repeated reclamation preserves the original created_at across multiple lease increments.
- Stale worker fencing:
    - Stale worker with outdated lease_version is fenced out after lease_assigned_at advances.
- History queries:
    - Chronological history ordering uses original created_at (not reclamation time).
    - Date filtering (created_after, created_before) accurately filters by original creation time.
- Alembic migration:
    - Migration 0005 backfills existing records using their created_at.
    - Isolated upgrade, downgrade, and re-upgrade roundtrip verification.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import io
import os
import shutil
import sqlite3
import tempfile
import uuid

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.identification_history import fetch_identification_history_list
from app.api.v1.identifications import get_current_provider
from app.core.config import settings
from app.identification.image_validation import validate_and_prepare
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


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalize SQLite naive datetime to UTC aware for strict comparison."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class MockInstantProvider(IdentificationProvider):
    @property
    def provider_id(self) -> str:
        return "mock-instant"

    async def identify(self, image: ImagePayload) -> ProviderResult:
        return ProviderResult(
            provider_id=self.provider_id,
            model_version="1.0.0",
            candidates=[
                ProviderCandidate(
                    scientific_name="Faurea saligna",
                    confidence=0.92,
                    family="Proteaceae",
                    genus="Faurea",
                    common_names=["African beech"],
                )
            ],
            provider_meta={"mode": "test_timestamp"},
        )


# ---------------------------------------------------------------------------
# 1. Timestamp Integrity Tests
# ---------------------------------------------------------------------------

class TestTimestampIntegrity:
    """Verifies that lease_assigned_at tracks lease timing while created_at is immutable."""

    async def test_initial_reservation_initializes_both_timestamps(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        req_id = f"test-ts-init-{uuid.uuid4()}"
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
        assert record.created_at is not None
        assert record.lease_assigned_at is not None

        # Both timestamps are set at request creation within millisecond delta
        delta = abs((record.lease_assigned_at - record.created_at).total_seconds())
        assert delta < 1.0

    async def test_reclamation_preserves_created_at_and_advances_lease_assigned_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        req_id = f"test-ts-reclaim-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()
        payload = validate_and_prepare(img_bytes, "image/jpeg")
        import hashlib
        sha = hashlib.sha256(payload.content).hexdigest()

        # Seed stalled reservation at lease_version = 1, created 150 seconds ago
        original_creation_time = datetime.now(timezone.utc) - timedelta(seconds=150)
        stalled = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=1,
            lease_assigned_at=original_creation_time,
            created_at=original_creation_time,
            image_sha256=sha,
            image_format="JPEG",
            image_size_bytes=len(img_bytes),
            image_width_px=10,
            image_height_px=10,
            provider_id="deterministic",
        )
        db_session.add(stalled)
        await db_session.commit()

        # Second worker reclaims the expired lease
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp.status_code == 200

        await db_session.refresh(stalled)
        assert stalled.status == "completed"
        assert stalled.lease_version == 2

        # CRITICAL ASSERTIONS:
        # 1. created_at must remain strictly immutable (matching original submission)
        assert _ensure_utc(stalled.created_at) == original_creation_time
        # 2. lease_assigned_at must have advanced to the reclamation time
        assert _ensure_utc(stalled.lease_assigned_at) > original_creation_time
        elapsed_advanced = (_ensure_utc(stalled.lease_assigned_at) - original_creation_time).total_seconds()
        assert elapsed_advanced >= 140.0

    async def test_failed_retry_preserves_created_at_and_advances_lease_assigned_at(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        req_id = f"test-ts-retry-{uuid.uuid4()}"
        img_bytes = _make_jpeg_bytes()
        payload = validate_and_prepare(img_bytes, "image/jpeg")
        import hashlib
        sha = hashlib.sha256(payload.content).hexdigest()

        original_creation_time = datetime.now(timezone.utc) - timedelta(seconds=300)
        failed_req = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=req_id,
            status="failed",
            outcome="failed",
            lease_version=1,
            lease_assigned_at=original_creation_time,
            created_at=original_creation_time,
            image_sha256=sha,
            image_format="JPEG",
            image_size_bytes=len(img_bytes),
            image_width_px=10,
            image_height_px=10,
            provider_id="deterministic",
            error_code="provider_timeout",
            error_message="Timed out initially",
            completed_at=original_creation_time + timedelta(seconds=60),
        )
        db_session.add(failed_req)
        await db_session.commit()

        # Client retries the request
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", img_bytes, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp.status_code == 200

        await db_session.refresh(failed_req)
        assert failed_req.status == "completed"
        assert failed_req.lease_version == 2

        # created_at remains immutable
        assert _ensure_utc(failed_req.created_at) == original_creation_time
        # lease_assigned_at advanced to retry time
        assert _ensure_utc(failed_req.lease_assigned_at) > original_creation_time

    async def test_repeated_reclamation_maintains_created_at(
        self, db_session: AsyncSession
    ):
        """Repeated lease renewals increment lease_version and advance lease_assigned_at while created_at never changes."""
        req_id = f"test-ts-multi-reclaim-{uuid.uuid4()}"
        record_id = uuid.uuid4()
        t0 = datetime.now(timezone.utc) - timedelta(seconds=300)

        record = IdentificationRequest(
            id=record_id,
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=1,
            lease_assigned_at=t0,
            created_at=t0,
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-1",
        )
        db_session.add(record)
        await db_session.commit()

        # Worker 2 reclaims at T1
        from sqlalchemy import update
        t1 = datetime.now(timezone.utc) - timedelta(seconds=120)
        stmt_w2 = (
            update(IdentificationRequest)
            .where(
                IdentificationRequest.id == record_id,
                IdentificationRequest.lease_version == 1,
                IdentificationRequest.status == "processing",
            )
            .values(
                lease_version=2,
                lease_assigned_at=t1,
                provider_id="worker-2",
            )
        )
        await db_session.execute(stmt_w2)
        await db_session.commit()

        # Worker 3 reclaims at T2
        t2 = datetime.now(timezone.utc)
        stmt_w3 = (
            update(IdentificationRequest)
            .where(
                IdentificationRequest.id == record_id,
                IdentificationRequest.lease_version == 2,
                IdentificationRequest.status == "processing",
            )
            .values(
                lease_version=3,
                lease_assigned_at=t2,
                provider_id="worker-3",
            )
        )
        await db_session.execute(stmt_w3)
        await db_session.commit()

        await db_session.refresh(record)
        assert record.lease_version == 3
        assert record.provider_id == "worker-3"
        assert _ensure_utc(record.created_at) == t0  # Still T0!
        assert _ensure_utc(record.lease_assigned_at) == t2

    async def test_stale_worker_fenced_after_timestamp_advancement(
        self, db_session: AsyncSession
    ):
        """Worker holding lease_version 1 cannot commit success after lease_assigned_at advanced to version 2."""
        req_id = f"test-ts-fenced-{uuid.uuid4()}"
        record_id = uuid.uuid4()
        t0 = datetime.now(timezone.utc) - timedelta(seconds=120)
        now = datetime.now(timezone.utc)

        record = IdentificationRequest(
            id=record_id,
            client_request_id=req_id,
            status="processing",
            outcome="processing",
            lease_version=2,  # Reclaimed by worker 2
            lease_assigned_at=now,
            created_at=t0,
            image_sha256="dummy_sha",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-2",
        )
        db_session.add(record)
        await db_session.commit()

        # Worker 1 (outdated lease_version 1) attempts to record success
        from app.schemas.identification import IdentificationCandidateOut
        candidate = IdentificationCandidateOut(
            scientific_name="Hibiscus rosa-sinensis",
            confidence=0.90,
            confidence_level=ConfidenceLevel.HIGH,
            catalogue_matched=True,
            catalogue_plant_id="hibiscus",
        )

        committed = await _record_success(
            db_session,
            record_id,
            expected_lease_version=1,  # Fenced!
            provider_id="worker-1",
            model_version="1.0.0",
            outcome=IdentificationOutcome.CANDIDATES,
            top_confidence_level=ConfidenceLevel.HIGH,
            execution_duration_ms=1000,
            enriched_candidates=[candidate],
            now=now,
        )

        assert committed is False
        await db_session.refresh(record)
        assert record.status == "processing"
        assert record.lease_version == 2

        # 0 candidates inserted
        cand_res = await db_session.execute(
            select(IdentificationCandidate).where(IdentificationCandidate.request_id == record_id)
        )
        assert len(cand_res.scalars().all()) == 0


# ---------------------------------------------------------------------------
# 2. History Ordering and Filter Tests
# ---------------------------------------------------------------------------

class TestHistoryOrderingAndFilters:
    """Verifies that history queries order and filter by immutable created_at."""

    async def test_history_ordering_chronological_by_original_created_at(
        self, db_session: AsyncSession
    ):
        base_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        t_a = base_time
        t_b = base_time + timedelta(minutes=2)
        reclaim_time_a = base_time + timedelta(minutes=5)

        # Request A created first at t_a, reclaimed later at reclaim_time_a
        req_a = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=f"test-hist-order-a-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=2,
            lease_assigned_at=reclaim_time_a,
            created_at=t_a,
            completed_at=reclaim_time_a + timedelta(seconds=2),
            image_sha256="dummy_sha_a",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-2",
        )

        # Request B created after A at t_b, completed immediately
        req_b = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=f"test-hist-order-b-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=1,
            lease_assigned_at=t_b,
            created_at=t_b,
            completed_at=t_b + timedelta(seconds=2),
            image_sha256="dummy_sha_b",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-1",
        )

        db_session.add_all([req_a, req_b])
        await db_session.commit()

        # Query history list: order_by is IdentificationRequest.created_at.desc()
        # B was created at t_a + 2m, A was created at t_a.
        # Therefore B must appear before A, despite A's lease reclamation at t_a + 5m!
        history = await fetch_identification_history_list(db_session, limit=10)
        matching_ids = [item.client_request_id for item in history.items if item.client_request_id in (req_a.client_request_id, req_b.client_request_id)]

        assert matching_ids == [req_b.client_request_id, req_a.client_request_id]

    async def test_history_date_filtering_uses_original_created_at(
        self, db_session: AsyncSession
    ):
        base_time = datetime.now(timezone.utc) - timedelta(hours=2)
        t_create = base_time
        t_reclaim = base_time + timedelta(hours=1)

        req = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=f"test-hist-filter-{uuid.uuid4()}",
            status="completed",
            outcome="candidates",
            lease_version=2,
            lease_assigned_at=t_reclaim,
            created_at=t_create,
            completed_at=t_reclaim + timedelta(seconds=2),
            image_sha256="dummy_sha_f",
            image_format="JPEG",
            image_size_bytes=100,
            provider_id="worker-2",
        )
        db_session.add(req)
        await db_session.commit()

        # Filter with created_before set to base_time + 10 minutes
        # Must match because original creation was at base_time (not t_reclaim)!
        cutoff = (base_time + timedelta(minutes=10)).isoformat()
        res = await fetch_identification_history_list(
            db_session,
            created_before=cutoff,
            limit=10,
        )
        found = any(item.client_request_id == req.client_request_id for item in res.items)
        assert found is True


# ---------------------------------------------------------------------------
# 3. Migration Roundtrip and Backfill Tests
# ---------------------------------------------------------------------------

class TestMigration0005Roundtrip:
    """Verifies that migration 0005 backfills existing records from created_at and supports clean rollback."""

    def test_migration_0005_backfill_and_roundtrip(self):
        from alembic import command
        from alembic.config import Config

        temp_dir = tempfile.mkdtemp()
        temp_db_path = os.path.join(temp_dir, "mig_test.db")
        clean_path = temp_db_path.replace("\\", "/")
        test_url = f"sqlite+aiosqlite:///{clean_path}"

        orig_url = settings.DATABASE_URL
        settings.DATABASE_URL = test_url

        try:
            cfg = Config("backend/alembic.ini")
            cfg.set_main_option("script_location", "backend/alembic")

            # 1. Upgrade to 0004
            command.upgrade(cfg, "0004_add_lease_fencing_and_candidate_rank_constraint")

            # Seed a historical record in 0004 schema with created_at
            conn = sqlite3.connect(temp_db_path)
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO identification_requests (
                    id, client_request_id, status, lease_version, image_sha256,
                    image_format, image_size_bytes, provider_id, outcome, created_at
                ) VALUES (
                    'seed-1', 'client-backfill-test', 'completed', 1, 'dummy_sha',
                    'JPEG', 100, 'deterministic', 'completed', '2026-10-15 08:30:00'
                )
                """
            )
            conn.commit()
            conn.close()

            # 2. Upgrade to 0005 (head)
            command.upgrade(cfg, "head")

            # Verify backfill populated lease_assigned_at with created_at
            conn = sqlite3.connect(temp_db_path)
            cur = conn.cursor()
            row = cur.execute(
                "SELECT created_at, lease_assigned_at FROM identification_requests WHERE id = 'seed-1'"
            ).fetchone()
            assert row[0] == "2026-10-15 08:30:00"
            assert row[1] == "2026-10-15 08:30:00", f"Backfill mismatch: {row[1]}"

            # Verify NOT NULL
            col_info = {
                c[1]: {"type": c[2], "notnull": c[3]}
                for c in cur.execute("PRAGMA table_info(identification_requests)").fetchall()
            }
            assert "lease_assigned_at" in col_info
            assert col_info["lease_assigned_at"]["notnull"] == 1

            # Verify index
            indices = [
                idx[1]
                for idx in cur.execute("PRAGMA index_list(identification_requests)").fetchall()
            ]
            assert "ix_identification_requests_lease_assigned_at" in indices

            # 3. Downgrade to 0004
            command.downgrade(cfg, "0004_add_lease_fencing_and_candidate_rank_constraint")
            cols_down = [
                c[1] for c in cur.execute("PRAGMA table_info(identification_requests)").fetchall()
            ]
            assert "lease_assigned_at" not in cols_down

            # 4. Re-upgrade to 0005
            command.upgrade(cfg, "head")
            cols_reup = [
                c[1] for c in cur.execute("PRAGMA table_info(identification_requests)").fetchall()
            ]
            assert "lease_assigned_at" in cols_reup
            conn.close()

        finally:
            settings.DATABASE_URL = orig_url
            shutil.rmtree(temp_dir, ignore_errors=True)
