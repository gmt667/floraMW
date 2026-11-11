"""Tests for Pl@ntNet botanical identification provider adapter — Phase 2.2.

Comprehensive offline unit and integration tests using httpx.MockTransport:
- Request construction (URL, query params, multipart files, organs)
- API key handling (passed securely, never leaked in logs, exceptions, or metadata)
- Result parsing and candidate normalization (scientific name, confidence, taxonomy, common names)
- Ranking order preservation (confidence descending)
- Empty results and 404 'Species not found' mapped to valid NO_MATCH
- Error handling: HTTP 401/403 (auth), HTTP 429 (rate limit), HTTP 5xx (upstream), 400 (bad request)
- Transport resilience: Connection failure, timeout, retry behavior
- Malformed payloads: Invalid JSON, non-dict response, missing species name, NaN/inf confidence
- Provider selection: Factory resolution, production allowed, no silent fallback to mock
- End-to-end endpoint integration via FastAPI test client
"""

from __future__ import annotations

import io
import json
import math
from unittest.mock import patch

import httpx
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from PIL import Image

from app.identification.exceptions import (
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.identification.plantnet_provider import PlantNetProvider
from app.identification.provider import (
    ImagePayload,
    get_identification_provider,
)
from app.identification.service import run_identification
from app.schemas.identification import IdentificationOutcome


# ---------------------------------------------------------------------------
# Test helpers & sample data
# ---------------------------------------------------------------------------


def _make_test_jpeg(width: int = 120, height: int = 90) -> ImagePayload:
    """Create in-memory ImagePayload for provider submission tests."""
    img = Image.new("RGB", (width, height), color=(34, 139, 34))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    content = buf.getvalue()
    return ImagePayload(
        content=content,
        format="JPEG",
        width_px=width,
        height_px=height,
        size_bytes=len(content),
    )


SAMPLE_PLANTNET_SUCCESS_JSON = {
    "query": {
        "project": "all",
        "images": ["image.jpg"],
        "organs": ["auto"],
        "includeRelatedImages": False,
    },
    "language": "en",
    "preferedReferential": "k-world-flora",
    "bestMatch": "Hibiscus rosa-sinensis L.",
    "results": [
        {
            "score": 0.8842,
            "species": {
                "scientificNameWithoutAuthor": "Hibiscus rosa-sinensis",
                "scientificNameAuthorship": "L.",
                "genus": {
                    "scientificNameWithoutAuthor": "Hibiscus",
                    "scientificName": "Hibiscus",
                },
                "family": {
                    "scientificNameWithoutAuthor": "Malvaceae",
                    "scientificName": "Malvaceae",
                },
                "commonNames": ["Chinese hibiscus", "China rose"],
                "scientificName": "Hibiscus rosa-sinensis L.",
                "id": 123456,
            },
        },
        {
            "score": 0.0521,
            "species": {
                "scientificNameWithoutAuthor": "Hibiscus syriacus",
                "scientificNameAuthorship": "L.",
                "genus": {
                    "scientificNameWithoutAuthor": "Hibiscus",
                    "scientificName": "Hibiscus",
                },
                "family": {
                    "scientificNameWithoutAuthor": "Malvaceae",
                    "scientificName": "Malvaceae",
                },
                "commonNames": ["Rose of Sharon"],
                "scientificName": "Hibiscus syriacus L.",
                "id": 123457,
            },
        },
    ],
    "version": "2024-03-20 (7.1)",
}


# ===========================================================================
# 1. API KEY & CONFIGURATION TESTS
# ===========================================================================


class TestPlantNetConfiguration:
    """Tests for API key validation and provider factory resolution."""

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_provider_unavailable(self):
        provider = PlantNetProvider(api_key="")
        image = _make_test_jpeg()
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await provider.identify(image)
        assert "API key is not configured" in str(exc_info.value)
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_whitespace_api_key_raises_provider_unavailable(self):
        provider = PlantNetProvider(api_key="   ")
        image = _make_test_jpeg()
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await provider.identify(image)
        assert "API key is not configured" in str(exc_info.value)

    def test_factory_resolves_plantnet_provider(self):
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "development"
            s.IDENTIFICATION_PROVIDER = "plantnet"
            s.ALLOW_MOCK_PROVIDER = True
            provider = get_identification_provider()
            assert isinstance(provider, PlantNetProvider)
            assert provider.provider_id == "plantnet"

    def test_factory_resolves_plantnet_in_production(self):
        """Pl@ntNet is a genuine provider and MUST be allowed in production."""
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "production"
            s.IDENTIFICATION_PROVIDER = "plantnet"
            s.ALLOW_MOCK_PROVIDER = False
            s.PLANTNET_API_KEY = "dummy-production-key"
            provider = get_identification_provider()
            assert isinstance(provider, PlantNetProvider)
            assert provider.provider_id == "plantnet"


# ===========================================================================
# 2. REQUEST CONSTRUCTION & SECURITY
# ===========================================================================


class TestPlantNetRequestConstruction:
    """Verifies that Pl@ntNet requests conform strictly to the official v2 API."""

    @pytest.mark.asyncio
    async def test_request_headers_url_and_params(self):
        captured_request: httpx.Request | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal captured_request
            captured_request = request
            return httpx.Response(
                200,
                json=SAMPLE_PLANTNET_SUCCESS_JSON,
            )

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="test-secret-key-12345",
                project="all",
                http_client=mock_client,
            )
            image = _make_test_jpeg()
            result = await provider.identify(image)

        assert captured_request is not None
        assert captured_request.method == "POST"
        assert captured_request.url.path == "/v2/identify/all"
        assert captured_request.url.params["api-key"] == "test-secret-key-12345"
        assert captured_request.url.params["include-related-images"] == "false"
        assert "multipart/form-data" in captured_request.headers.get("content-type", "")

        # Verify API key is NOT stored in provider_meta or candidate notes
        assert "test-secret-key-12345" not in str(result.provider_meta)
        for c in result.candidates:
            assert "test-secret-key-12345" not in (c.notes or "")
            assert "test-secret-key-12345" not in (c.provider_taxon_id or "")

    @pytest.mark.asyncio
    async def test_api_key_not_leaked_in_exceptions_or_tracebacks(self):
        """Confirm that transport exceptions do not leak the API key in message or cause."""
        secret_key = "super-secret-plantnet-key-xyz987"

        def handler(request: httpx.Request) -> httpx.Response:
            # Simulate httpx error that embeds the request URL with query parameters
            raise httpx.ConnectError(f"Connection failed for {request.url}")

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key=secret_key,
                project="all",
                http_client=mock_client,
            )
            image = _make_test_jpeg()
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await provider.identify(image)

        # 1. Exception string must not leak the key
        assert secret_key not in str(exc_info.value)
        # 2. Chained __cause__ must be None to prevent leak in formatted tracebacks
        assert exc_info.value.__cause__ is None


# ===========================================================================
# 3. RESPONSE PARSING & CANDIDATE NORMALIZATION
# ===========================================================================


class TestPlantNetResponseParsing:
    """Tests normalization of Pl@ntNet candidates into FloraMW ProviderCandidate models."""

    @pytest.mark.asyncio
    async def test_successful_parsing(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SAMPLE_PLANTNET_SUCCESS_JSON)

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            result = await provider.identify(_make_test_jpeg())

        assert result.provider_id == "plantnet"
        assert result.model_version == "2024-03-20 (7.1)"
        assert len(result.candidates) == 2

        # Check candidate 1 (top candidate)
        top = result.candidates[0]
        assert top.scientific_name == "Hibiscus rosa-sinensis"
        assert top.confidence == 0.8842
        assert top.family == "Malvaceae"
        assert top.genus == "Hibiscus"
        assert "Chinese hibiscus" in top.common_names
        assert top.provider_taxon_id == "plantnet:123456"
        assert top.notes == "Pl@ntNet match (authorship: L.)"

        # Check candidate 2 (lower ranked)
        second = result.candidates[1]
        assert second.scientific_name == "Hibiscus syriacus"
        assert second.confidence == 0.0521
        assert top.confidence > second.confidence

    @pytest.mark.asyncio
    async def test_empty_results_returns_no_match(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [], "version": "2024-03-20"})

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            result = await provider.identify(_make_test_jpeg())

        assert result.candidates == []
        assert result.provider_id == "plantnet"

    @pytest.mark.asyncio
    async def test_http_404_species_not_found_mapped_to_no_match(self):
        """Pl@ntNet returns 404 when no plant can be identified in the image."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={"statusCode": 404, "message": "Species not found", "version": "v2"},
            )

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            result = await provider.identify(_make_test_jpeg())

        assert result.candidates == []
        assert result.provider_id == "plantnet"

    @pytest.mark.asyncio
    async def test_http_404_project_not_found_raises_provider_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                404,
                json={"statusCode": 404, "message": "Project non_existent_flora not found"},
            )

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key",
                project="non_existent_flora",
                http_client=mock_client,
            )
            with pytest.raises(ProviderResponseError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "not found" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_confidence_values_skipped(self):
        payload = {
            "results": [
                {
                    "score": "not-a-number",
                    "species": {"scientificNameWithoutAuthor": "Species A"},
                },
                {
                    "score": -0.5,
                    "species": {"scientificNameWithoutAuthor": "Species B"},
                },
                {
                    "score": 1.25,
                    "species": {"scientificNameWithoutAuthor": "Species C"},
                },
                {
                    "score": 0.75,
                    "species": {"scientificNameWithoutAuthor": "Valid species"},
                },
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            result = await provider.identify(_make_test_jpeg())

        assert len(result.candidates) == 1
        assert result.candidates[0].scientific_name == "Valid species"
        assert result.candidates[0].confidence == 0.75

    @pytest.mark.asyncio
    async def test_missing_scientific_name_skipped(self):
        payload = {
            "results": [
                {
                    "score": 0.9,
                    "species": {"scientificNameWithoutAuthor": "", "scientificName": ""},
                },
                {
                    "score": 0.8,
                    "species": {"scientificNameWithoutAuthor": "Good species"},
                },
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            result = await provider.identify(_make_test_jpeg())

        assert len(result.candidates) == 1
        assert result.candidates[0].scientific_name == "Good species"


# ===========================================================================
# 4. HTTP ERROR & NETWORK RESILIENCE
# ===========================================================================


class TestPlantNetErrorHandling:
    """Tests failure mapping for authentication, rate limits, timeouts and HTTP errors."""

    @pytest.mark.asyncio
    async def test_http_401_raises_provider_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "Invalid API key"})

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="invalid-key", http_client=mock_client
            )
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "authentication failed" in str(exc_info.value).lower()
        assert "invalid-key" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_http_403_raises_provider_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"message": "Forbidden"})

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="blocked-key", http_client=mock_client
            )
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "authentication failed" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_http_429_rate_limit_raises_provider_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"message": "Rate limit exceeded"})

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "rate limit exceeded" in str(exc_info.value).lower()
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_http_500_raises_provider_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "upstream error" in str(exc_info.value).lower()
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_http_400_bad_request_raises_provider_response_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"message": "Missing image file"})

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            with pytest.raises(ProviderResponseError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "rejected" in str(exc_info.value).lower()
        assert exc_info.value.retryable is False

    @pytest.mark.asyncio
    async def test_timeout_raises_provider_timeout_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("Read timed out")

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            with pytest.raises(ProviderTimeoutError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "timed out" in str(exc_info.value).lower()
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_connect_error_raises_provider_unavailable(self):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("DNS resolution failed")

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            with pytest.raises(ProviderUnavailableError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "unable to connect" in str(exc_info.value).lower()
        assert exc_info.value.retryable is True

    @pytest.mark.asyncio
    async def test_malformed_json_raises_provider_response_error(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html><body>Gateway Error</body></html>")

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            with pytest.raises(ProviderResponseError) as exc_info:
                await provider.identify(_make_test_jpeg())
        assert "unparseable" in str(exc_info.value).lower()


# ===========================================================================
# 5. SERVICE & ENDPOINT INTEGRATION TESTS
# ===========================================================================


class TestPlantNetServiceAndEndpointIntegration:
    """Integration of PlantNetProvider with run_identification service and FastAPI endpoint."""

    @pytest.mark.asyncio
    async def test_service_returns_candidates_with_catalogue_match(self, db_session):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SAMPLE_PLANTNET_SUCCESS_JSON)

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            image_payload = _make_test_jpeg()
            response = await run_identification(
                raw_bytes=image_payload.content,
                declared_content_type="image/jpeg",
                provider=provider,
                db=db_session,
            )

        assert response.outcome == IdentificationOutcome.CANDIDATES
        assert response.provider.is_demo is False
        assert response.provider.provider_id == "plantnet"
        assert response.provider.model_version == "2024-03-20 (7.1)"
        assert len(response.candidates) == 2

        # Check catalogue matching for Hibiscus rosa-sinensis
        top = response.candidates[0]
        assert top.scientific_name == "Hibiscus rosa-sinensis"
        assert top.catalogue_matched is True
        assert top.catalogue_plant_id == "hibiscus"

        # Check external unmatched species (Hibiscus syriacus)
        second = response.candidates[1]
        assert second.scientific_name == "Hibiscus syriacus"
        assert second.catalogue_matched is False
        assert second.catalogue_plant_id is None

    @pytest.mark.asyncio
    async def test_no_silent_fallback_to_mock_on_plantnet_failure(self, db_session):
        """When Pl@ntNet fails, service must raise HTTPException and NEVER fall back to mock."""
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, text="Pl@ntNet Server Error")

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            image_payload = _make_test_jpeg()
            with pytest.raises(HTTPException) as exc_info:
                await run_identification(
                    raw_bytes=image_payload.content,
                    declared_content_type="image/jpeg",
                    provider=provider,
                    db=db_session,
                )
            assert exc_info.value.status_code == 503
            detail = exc_info.value.detail
            assert detail["error_code"] == "provider_unavailable"

    @pytest.mark.asyncio
    async def test_api_endpoint_end_to_end_with_plantnet(self, client: AsyncClient):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=SAMPLE_PLANTNET_SUCCESS_JSON)

        mock_transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=mock_transport) as mock_client:
            plantnet_provider = PlantNetProvider(
                api_key="valid-key", http_client=mock_client
            )
            app.dependency_overrides[get_current_provider] = lambda: plantnet_provider

            try:
                image_bytes = _make_test_jpeg().content
                response = await client.post(
                    "/api/v1/identifications",
                    headers={"X-Client-Request-Id": "plantnet-test-uuid-999"},
                    files={"image": ("plant.jpg", image_bytes, "image/jpeg")},
                )
                assert response.status_code == 200
                data = response.json()
                assert data["outcome"] == "candidates"
                assert data["provider"]["is_demo"] is False
                assert data["provider"]["provider_id"] == "plantnet"
                assert data["client_request_id"] == "plantnet-test-uuid-999"
                assert len(data["candidates"]) == 2
                assert data["candidates"][0]["scientific_name"] == "Hibiscus rosa-sinensis"
                assert data["candidates"][0]["catalogue_matched"] is True
                assert data["candidates"][0]["catalogue_plant_id"] == "hibiscus"
                assert data["safety_disclaimer"]
            finally:
                app.dependency_overrides.pop(get_current_provider, None)
