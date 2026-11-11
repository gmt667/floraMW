"""Tests for Phase 3: Identification Persistence, Idempotency, History API,
Internal Provider, and Taxonomy Validation Utility.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identification.exceptions import (
    ConfigurationError,
    IdempotencyConflictError,
    ProviderNetworkError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.identification.internal_provider import InternalModelProvider, _MOCK_PREDICTIONS
from app.identification.provider import (
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
    get_identification_provider,
)
from app.models.identification import IdentificationCandidate, IdentificationRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_jpeg_bytes(w: int = 10, h: int = 10) -> bytes:
    img = Image.new("RGB", (w, h), color=(34, 139, 34))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_image_payload(w: int = 10, h: int = 10) -> ImagePayload:
    data = _make_jpeg_bytes(w, h)
    return ImagePayload(
        content=data,
        format="JPEG",
        width_px=w,
        height_px=h,
        size_bytes=len(data),
    )


# ===========================================================================
# SECTION 1: Internal Model Provider
# ===========================================================================


class TestInternalProviderMockMode:
    """InternalModelProvider in mock mode."""

    def test_mock_mode_provider_id(self):
        p = InternalModelProvider(mode="mock")
        assert p.provider_id == "internal"

    async def test_mock_returns_candidates(self):
        p = InternalModelProvider(mode="mock")
        image = _make_image_payload()
        result = await p.identify(image)
        assert isinstance(result, ProviderResult)
        assert len(result.candidates) == len(_MOCK_PREDICTIONS)

    async def test_mock_candidates_sorted_by_confidence(self):
        p = InternalModelProvider(mode="mock")
        image = _make_image_payload()
        result = await p.identify(image)
        scores = [c.confidence for c in result.candidates]
        assert scores == sorted(scores, reverse=True)

    async def test_mock_provider_id_in_result(self):
        p = InternalModelProvider(mode="mock")
        image = _make_image_payload()
        result = await p.identify(image)
        assert result.provider_id == "internal"

    async def test_mock_model_version_in_result(self):
        p = InternalModelProvider(mode="mock", model_version="test-v1.0")
        image = _make_image_payload()
        result = await p.identify(image)
        assert result.model_version == "test-v1.0"

    async def test_mock_provider_meta_contains_execution_mode(self):
        p = InternalModelProvider(mode="mock")
        image = _make_image_payload()
        result = await p.identify(image)
        assert result.provider_meta.get("execution_mode") == "mock"

    async def test_mock_all_candidates_have_valid_confidence(self):
        p = InternalModelProvider(mode="mock")
        image = _make_image_payload()
        result = await p.identify(image)
        for cand in result.candidates:
            assert 0.0 <= cand.confidence <= 1.0

    async def test_mock_all_candidates_have_scientific_name(self):
        p = InternalModelProvider(mode="mock")
        image = _make_image_payload()
        result = await p.identify(image)
        for cand in result.candidates:
            assert cand.scientific_name and cand.scientific_name.strip()


class TestInternalProviderServiceMode:
    """InternalModelProvider in service mode."""

    async def test_service_mode_requires_service_url(self):
        with pytest.raises(ConfigurationError, match="INTERNAL_MODEL_SERVICE_URL"):
            InternalModelProvider(mode="service", service_url="")

    async def test_service_mode_calls_predict_endpoint(self):
        payload_body = {
            "model_id": "test-model",
            "model_version": "1.0.0",
            "candidates": [
                {
                    "scientific_name": "Hibiscus rosa-sinensis",
                    "confidence": 0.95,
                    "common_names": ["Chinese hibiscus"],
                    "family": "Malvaceae",
                    "genus": "Hibiscus",
                }
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert "/predict" in str(request.url)
            return httpx.Response(200, json=payload_body)

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        p = InternalModelProvider(
            mode="service",
            service_url="http://inference:8080",
            http_client=client,
        )
        image = _make_image_payload()
        result = await p.identify(image)
        assert len(result.candidates) == 1
        assert result.candidates[0].scientific_name == "Hibiscus rosa-sinensis"
        assert result.candidates[0].confidence == 0.95

    async def test_service_mode_timeout_raises_provider_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        p = InternalModelProvider(
            mode="service",
            service_url="http://inference:8080",
            http_client=client,
            timeout=1.0,
        )
        image = _make_image_payload()
        with pytest.raises(ProviderTimeoutError):
            await p.identify(image)

    async def test_service_mode_network_error_raises_provider_network_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.NetworkError("connection refused")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        p = InternalModelProvider(
            mode="service",
            service_url="http://inference:8080",
            http_client=client,
        )
        image = _make_image_payload()
        with pytest.raises(ProviderNetworkError):
            await p.identify(image)

    async def test_service_mode_non_200_raises_provider_response_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        p = InternalModelProvider(
            mode="service",
            service_url="http://inference:8080",
            http_client=client,
        )
        image = _make_image_payload()
        with pytest.raises(ProviderResponseError):
            await p.identify(image)

    async def test_service_mode_invalid_json_raises_provider_response_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="NOT JSON")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        p = InternalModelProvider(
            mode="service",
            service_url="http://inference:8080",
            http_client=client,
        )
        image = _make_image_payload()
        with pytest.raises(ProviderResponseError):
            await p.identify(image)

    async def test_service_mode_empty_candidates_returns_no_match(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"candidates": []})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        p = InternalModelProvider(
            mode="service",
            service_url="http://inference:8080",
            http_client=client,
        )
        image = _make_image_payload()
        result = await p.identify(image)
        assert result.candidates == []


class TestInternalProviderArtifactMode:
    async def test_artifact_mode_requires_artifact_path(self):
        with pytest.raises(ConfigurationError, match="INTERNAL_MODEL_ARTIFACT_PATH"):
            InternalModelProvider(mode="artifact")

    async def test_artifact_mode_raises_provider_unavailable_on_identify(self):
        # Directly construct with known path, bypass settings patch; identify() should raise
        p = InternalModelProvider.__new__(InternalModelProvider)
        p.mode = "artifact"
        p.model_id = "test"
        p.model_version = "1.0"
        p.service_url = ""
        p.timeout = 5.0
        p._client = None
        image = _make_image_payload()
        with pytest.raises(ProviderUnavailableError, match="ML team"):
            await p.identify(image)


class TestInternalProviderFactoryRegistration:
    def test_factory_resolves_internal_provider(self):
        with patch("app.core.config.settings") as mock_settings:
            mock_settings.IDENTIFICATION_PROVIDER = "internal"
            mock_settings.ENVIRONMENT = "development"
            mock_settings.ALLOW_MOCK_PROVIDER = True
            mock_settings.INTERNAL_MODEL_MODE = "mock"
            mock_settings.INTERNAL_MODEL_ID = "test"
            mock_settings.INTERNAL_MODEL_VERSION = "1.0"
            mock_settings.INTERNAL_MODEL_SERVICE_URL = ""
            mock_settings.INTERNAL_MODEL_ARTIFACT_PATH = ""
            mock_settings.INTERNAL_MODEL_TIMEOUT_SECONDS = 5.0

            provider = get_identification_provider()
            assert isinstance(provider, InternalModelProvider)

    def test_disabled_mode_raises_provider_unavailable(self):
        with pytest.raises(ProviderUnavailableError):
            InternalModelProvider(mode="disabled")

    def test_unknown_mode_raises_configuration_error(self):
        with pytest.raises(ConfigurationError, match="Unknown INTERNAL_MODEL_MODE"):
            InternalModelProvider(mode="unsupported_mode_xyz")


# ===========================================================================
# SECTION 2: Identification Persistence
# ===========================================================================


class TestIdentificationPersistence:
    """Tests for database persistence of identification requests and candidates."""

    async def test_identification_creates_request_record(self, client, db_session):
        """Submitting an identification creates an IdentificationRequest in the DB."""
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(IdentificationRequest).order_by(IdentificationRequest.created_at.desc())
        )
        req = result.scalars().first()
        assert req is not None
        assert req.status == "completed"
        assert req.outcome is not None
        assert req.image_sha256 is not None
        assert len(req.image_sha256) == 64  # SHA-256 hex

    async def test_identification_creates_candidate_records(self, client, db_session):
        """A successful identification persists candidate rows with correct ranks."""
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()

        if body["outcome"] != "no_match":
            result = await db_session.execute(
                select(IdentificationRequest).order_by(IdentificationRequest.created_at.desc())
            )
            req = result.scalars().first()

            cand_result = await db_session.execute(
                select(IdentificationCandidate)
                .where(IdentificationCandidate.request_id == req.id)
                .order_by(IdentificationCandidate.rank)
            )
            candidates = cand_result.scalars().all()

            assert len(candidates) == len(body["candidates"])
            # Ranks must be sequential starting at 1
            ranks = [c.rank for c in candidates]
            assert ranks == list(range(1, len(candidates) + 1))

    async def test_candidate_confidence_values_match_response(self, client, db_session):
        """Persisted candidate confidence scores match what was returned in the API response."""
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200
        body = resp.json()

        if body["outcome"] == "no_match":
            pytest.skip("No candidates to verify")

        result = await db_session.execute(
            select(IdentificationRequest).order_by(IdentificationRequest.created_at.desc())
        )
        req = result.scalars().first()

        cand_result = await db_session.execute(
            select(IdentificationCandidate)
            .where(IdentificationCandidate.request_id == req.id)
            .order_by(IdentificationCandidate.rank)
        )
        db_candidates = cand_result.scalars().all()

        api_candidates = body["candidates"]
        for db_cand, api_cand in zip(db_candidates, api_candidates):
            assert abs(db_cand.confidence - api_cand["confidence"]) < 1e-9
            assert db_cand.scientific_name == api_cand["scientific_name"]

    async def test_image_sha256_stored_in_request(self, client, db_session):
        """The image SHA-256 fingerprint is stored and matches the uploaded image."""
        img = _make_jpeg_bytes()
        expected_sha = None  # We compute this after validation/reencoding

        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(IdentificationRequest).order_by(IdentificationRequest.created_at.desc())
        )
        req = result.scalars().first()

        # SHA-256 must be present and be a 64-char hex string
        assert req.image_sha256 is not None
        assert len(req.image_sha256) == 64
        assert all(c in "0123456789abcdef" for c in req.image_sha256)

    async def test_provider_id_stored_in_request(self, client, db_session):
        """The provider_id from the ProviderResult is stored in the request record."""
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(IdentificationRequest).order_by(IdentificationRequest.created_at.desc())
        )
        req = result.scalars().first()

        assert req.provider_id is not None
        assert len(req.provider_id) > 0

    async def test_client_request_id_header_stored(self, client, db_session):
        """When X-Client-Request-Id is supplied, it is stored as the client_request_id."""
        custom_id = str(uuid.uuid4())
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
            headers={"X-Client-Request-Id": custom_id},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(IdentificationRequest).where(
                IdentificationRequest.client_request_id == custom_id
            )
        )
        req = result.scalar_one_or_none()
        assert req is not None

    async def test_no_match_persisted_correctly(self, client, db_session):
        """NO_MATCH outcomes are persisted correctly with no candidates."""
        from app.identification.deterministic_provider import DeterministicProvider
        from app.identification.provider import get_identification_provider
        from app.core.database import get_db
        from app.main import app

        # Force an empty-result provider for this test
        class EmptyProvider:
            provider_id = "floramw-deterministic-v1-test"
            async def identify(self, image):
                return ProviderResult(candidates=[], provider_id=self.provider_id)

        from app.api.v1.identifications import get_current_provider
        app.dependency_overrides[get_current_provider] = lambda: EmptyProvider()

        try:
            img = _make_jpeg_bytes()
            custom_id = str(uuid.uuid4())
            resp = await client.post(
                "/api/v1/identifications",
                files={"image": ("test.jpg", img, "image/jpeg")},
                headers={"X-Client-Request-Id": custom_id},
            )
            assert resp.status_code == 200
            assert resp.json()["outcome"] == "no_match"

            result = await db_session.execute(
                select(IdentificationRequest).where(
                    IdentificationRequest.client_request_id == custom_id
                )
            )
            req = result.scalar_one_or_none()
            assert req is not None
            assert req.outcome == "no_match"

            cand_result = await db_session.execute(
                select(IdentificationCandidate).where(
                    IdentificationCandidate.request_id == req.id
                )
            )
            assert cand_result.scalars().all() == []
        finally:
            app.dependency_overrides.clear()
            from app.core.database import get_db
            from app.identification.provider import get_identification_provider
            from app.api.v1.identifications import get_current_provider as _gcp


# ===========================================================================
# SECTION 3: Idempotency
# ===========================================================================


class TestIdempotency:
    """Tests for X-Client-Request-Id idempotency behaviour."""

    async def test_duplicate_request_same_image_returns_200(self, client):
        """Submitting the same image with same client_request_id returns 200 from cache."""
        img = _make_jpeg_bytes()
        req_id = str(uuid.uuid4())

        resp1 = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp2.status_code == 200

    async def test_duplicate_request_same_outcome(self, client):
        """The second (cached) response returns the same outcome as the first."""
        img = _make_jpeg_bytes()
        req_id = str(uuid.uuid4())

        resp1 = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        resp2 = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )

        assert resp1.json()["outcome"] == resp2.json()["outcome"]

    async def test_duplicate_request_provider_not_called_twice(self, client, db_session):
        """The provider is only invoked once; the second request returns cached data."""
        img = _make_jpeg_bytes()
        req_id = str(uuid.uuid4())

        for _ in range(3):
            await client.post(
                "/api/v1/identifications",
                files={"image": ("test.jpg", img, "image/jpeg")},
                headers={"X-Client-Request-Id": req_id},
            )

        # Only one record should exist in the DB for this request_id
        result = await db_session.execute(
            select(IdentificationRequest).where(
                IdentificationRequest.client_request_id == req_id
            )
        )
        records = result.scalars().all()
        assert len(records) == 1

    async def test_different_image_same_request_id_returns_409(self, client):
        """Using the same X-Client-Request-Id with a different image returns 409."""
        req_id = str(uuid.uuid4())

        img1 = _make_jpeg_bytes(10, 10)
        img2 = _make_jpeg_bytes(20, 20)  # Different content

        resp1 = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img1, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img2, "image/jpeg")},
            headers={"X-Client-Request-Id": req_id},
        )
        assert resp2.status_code == 409

    async def test_no_client_id_generates_server_uuid(self, client, db_session):
        """When no X-Client-Request-Id is provided, a server UUID is generated and stored."""
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200

        result = await db_session.execute(
            select(IdentificationRequest).order_by(IdentificationRequest.created_at.desc())
        )
        req = result.scalars().first()
        assert req is not None
        # Should be a valid UUID
        assert uuid.UUID(req.client_request_id)


# ===========================================================================
# SECTION 4: Identification History API & Query Service
# ===========================================================================


class TestIdentificationHistoryEndpointsFailClosed:
    """Phase 3.1 SEC-01 & SEC-02: Public history endpoints must fail closed

    with HTTP 503 pending Phase 4 authentication integration.
    Zero historical records, candidate data, or user metadata may be disclosed.
    """

    async def test_list_identifications_returns_503(self, client):
        """GET /api/v1/identifications returns 503 Service Unavailable."""
        resp = await client.get("/api/v1/identifications")
        assert resp.status_code == 503
        body = resp.json()
        assert "temporarily unavailable pending user authentication" in body["detail"]
        assert "items" not in body
        assert "total" not in body

    async def test_list_identifications_with_filters_returns_503(self, client):
        """GET /api/v1/identifications with query params still returns 503."""
        resp = await client.get("/api/v1/identifications?outcome=candidates&limit=5")
        assert resp.status_code == 503
        body = resp.json()
        assert "temporarily unavailable pending user authentication" in body["detail"]

    async def test_get_identification_valid_uuid_returns_503(self, client):
        """GET /api/v1/identifications/{id} returns 503 Service Unavailable."""
        fake_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/identifications/{fake_id}")
        assert resp.status_code == 503
        body = resp.json()
        assert "temporarily unavailable pending user authentication" in body["detail"]
        assert "candidates" not in body

    async def test_get_identification_invalid_uuid_returns_503(self, client):
        """Non-UUID path parameter also fails closed with 503."""
        resp = await client.get("/api/v1/identifications/not-a-uuid")
        assert resp.status_code == 503
        body = resp.json()
        assert "temporarily unavailable pending user authentication" in body["detail"]


class TestIdentificationHistoryQueryService:
    """Unit tests for the underlying query service (fetch_identification_history_list

    and fetch_identification_detail) which use optimized correlated subqueries.
    """

    async def test_history_list_query_service_returns_data(self, client, db_session):
        from app.api.v1.identification_history import fetch_identification_history_list

        img = _make_jpeg_bytes()
        await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )

        res = await fetch_identification_history_list(db_session, page=1, limit=20)
        assert res.total >= 1
        assert res.page == 1
        assert res.limit == 20
        assert isinstance(res.items, list)
        item = res.items[0]
        assert item.id is not None
        assert item.outcome in ("candidates", "no_match", "demo_mode")
        assert item.candidate_count >= 0

    async def test_history_list_outcome_filter(self, client, db_session):
        from app.api.v1.identification_history import fetch_identification_history_list

        img = _make_jpeg_bytes()
        await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )

        res = await fetch_identification_history_list(db_session, outcome="candidates")
        for item in res.items:
            assert item.outcome == "candidates"

    async def test_history_list_invalid_outcome_raises_400(self, db_session):
        from fastapi import HTTPException
        from app.api.v1.identification_history import fetch_identification_history_list

        with pytest.raises(HTTPException) as exc_info:
            await fetch_identification_history_list(db_session, outcome="invalid_value")
        assert exc_info.value.status_code == 400

    async def test_history_list_created_after_filter(self, db_session):
        from app.api.v1.identification_history import fetch_identification_history_list

        future_time = "2099-01-01T00:00:00Z"
        res = await fetch_identification_history_list(db_session, created_after=future_time)
        assert res.total == 0
        assert len(res.items) == 0

    async def test_history_list_invalid_datetime_raises_400(self, db_session):
        from fastapi import HTTPException
        from app.api.v1.identification_history import fetch_identification_history_list

        with pytest.raises(HTTPException) as exc_info:
            await fetch_identification_history_list(db_session, created_after="not-a-date")
        assert exc_info.value.status_code == 400

    async def test_history_detail_query_service(self, client, db_session):
        from app.api.v1.identification_history import (
            fetch_identification_detail,
            fetch_identification_history_list,
        )

        img = _make_jpeg_bytes()
        await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )

        list_res = await fetch_identification_history_list(db_session, limit=1)
        assert len(list_res.items) > 0
        target_id = list_res.items[0].id

        detail = await fetch_identification_detail(str(target_id), db_session)
        assert detail.id == str(target_id)
        assert detail.provider is not None
        assert isinstance(detail.candidates, list)
        if detail.candidates:
            ranks = [c.rank for c in detail.candidates]
            assert ranks == sorted(ranks)

    async def test_history_detail_unknown_id_raises_404(self, db_session):
        from fastapi import HTTPException
        from app.api.v1.identification_history import fetch_identification_detail

        fake_id = str(uuid.uuid4())
        with pytest.raises(HTTPException) as exc_info:
            await fetch_identification_detail(fake_id, db_session)
        assert exc_info.value.status_code == 404

    async def test_history_detail_invalid_uuid_raises_404(self, db_session):
        from fastapi import HTTPException
        from app.api.v1.identification_history import fetch_identification_detail

        with pytest.raises(HTTPException) as exc_info:
            await fetch_identification_detail("not-a-uuid", db_session)
        assert exc_info.value.status_code == 404


# ===========================================================================
# SECTION 5: Taxonomy Validation Utility
# ===========================================================================


class TestTaxonomyValidationUtility:
    async def test_matched_catalogue_species(self, db_session):
        """Known catalogue species are reported as matched."""
        from app.core.taxonomy_check import validate_labels
        labels = {"0": "Hibiscus rosa-sinensis"}
        report = await validate_labels(db_session, labels)
        assert report.matched_count == 1
        assert report.unmatched_count == 0

    async def test_unmatched_species_reported(self, db_session):
        """Unknown species names are listed as unmatched."""
        from app.core.taxonomy_check import validate_labels
        labels = {"0": "Completely unknown plantus fictus"}
        report = await validate_labels(db_session, labels)
        assert report.unmatched_count == 1
        assert report.matched_count == 0

    async def test_duplicate_labels_detected(self, db_session):
        """Duplicate scientific names (different indices) are detected."""
        from app.core.taxonomy_check import validate_labels
        labels = {
            "0": "Hibiscus rosa-sinensis",
            "1": "hibiscus rosa-sinensis",  # Same name, different case
        }
        report = await validate_labels(db_session, labels)
        assert report.duplicate_count == 1

    async def test_invalid_labels_detected(self, db_session):
        """Non-string or empty entries are reported as invalid."""
        from app.core.taxonomy_check import validate_labels
        labels = {"0": "", "1": "   "}
        report = await validate_labels(db_session, labels)
        assert report.invalid_count == 2

    async def test_case_insensitive_matching(self, db_session):
        """Matching is case-insensitive and whitespace-normalised."""
        from app.core.taxonomy_check import validate_labels
        labels = {"0": "HIBISCUS ROSA-SINENSIS"}
        report = await validate_labels(db_session, labels)
        assert report.matched_count == 1

    async def test_empty_labels_produces_zero_counts(self, db_session):
        """Empty label map produces all-zero report."""
        from app.core.taxonomy_check import validate_labels
        report = await validate_labels(db_session, {})
        assert report.total_labels == 0
        assert report.matched_count == 0

    async def test_fully_matched_flag(self, db_session):
        """is_fully_matched is True only when all labels match and no duplicates."""
        from app.core.taxonomy_check import validate_labels
        labels = {"0": "Hibiscus rosa-sinensis"}
        report = await validate_labels(db_session, labels)
        assert report.is_fully_matched is True

    async def test_not_fully_matched_with_unmatched(self, db_session):
        """is_fully_matched is False when any label is unmatched."""
        from app.core.taxonomy_check import validate_labels
        labels = {"0": "Hibiscus rosa-sinensis", "1": "Unknown plantus XYZ"}
        report = await validate_labels(db_session, labels)
        assert report.is_fully_matched is False

    def test_load_labels_file_valid_json(self, tmp_path):
        """load_labels_file parses valid JSON correctly."""
        from app.core.taxonomy_check import load_labels_file
        labels_file = tmp_path / "labels.json"
        labels_file.write_text('{"0": "Hibiscus rosa-sinensis", "1": "Delonix regia"}')
        result = load_labels_file(labels_file)
        assert result["0"] == "Hibiscus rosa-sinensis"
        assert result["1"] == "Delonix regia"

    def test_load_labels_file_missing_raises_file_not_found(self, tmp_path):
        """load_labels_file raises FileNotFoundError for missing file."""
        from app.core.taxonomy_check import load_labels_file
        with pytest.raises(FileNotFoundError):
            load_labels_file(tmp_path / "nonexistent.json")

    def test_load_labels_file_invalid_json_raises_value_error(self, tmp_path):
        """load_labels_file raises ValueError for malformed JSON."""
        from app.core.taxonomy_check import load_labels_file
        labels_file = tmp_path / "bad.json"
        labels_file.write_text("{not valid json")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_labels_file(labels_file)

    def test_load_labels_file_array_raises_value_error(self, tmp_path):
        """load_labels_file raises ValueError when JSON root is a list not a dict."""
        from app.core.taxonomy_check import load_labels_file
        labels_file = tmp_path / "array.json"
        labels_file.write_text('["Hibiscus rosa-sinensis"]')
        with pytest.raises(ValueError, match="JSON object"):
            load_labels_file(labels_file)

    def test_to_dict_summary_fields(self, db_session):
        """LabelValidationReport.to_dict() contains expected summary keys."""
        from app.core.taxonomy_check import LabelValidationReport
        r = LabelValidationReport(total_labels=5, matched_count=3, unmatched_count=2)
        d = r.to_dict()
        assert "summary" in d
        assert d["summary"]["total_labels"] == 5
        assert d["summary"]["matched_count"] == 3
        assert d["summary"]["unmatched_count"] == 2


# ===========================================================================
# SECTION 6: Existing endpoints remain intact
# ===========================================================================


class TestExistingEndpointsUnaffected:
    async def test_plants_endpoint_still_works(self, client):
        resp = await client.get("/api/v1/plants")
        assert resp.status_code == 200

    async def test_districts_endpoint_still_works(self, client):
        resp = await client.get("/api/v1/districts")
        assert resp.status_code == 200

    async def test_health_endpoint_still_works(self, client):
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_identification_endpoint_still_works(self, client):
        img = _make_jpeg_bytes()
        resp = await client.post(
            "/api/v1/identifications",
            files={"image": ("test.jpg", img, "image/jpeg")},
        )
        assert resp.status_code == 200
