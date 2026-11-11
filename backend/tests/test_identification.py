"""Tests for the botanical plant identification engine — Phase 2.1.

Coverage:
- Image validation (valid JPEG, PNG, empty, corrupted, oversized, bad format, MIME mismatch)
- Provider contract (candidates, no-match, unavailable, timeout, bad payload)
- Provider configuration & production safety (environment gate, mock allowed/forbidden, unconfigured)
- Candidate validation (math.isfinite, NaN, Infinity, out-of-range, ordering)
- Identification service (catalogue match, unmatched species, low confidence, HTTP status exceptions)
- API endpoint (successful request, structured 200 response, client request ID header,
  proper HTTP errors: 400, 413, 415, 422, 502, 503, 504, safety disclaimer in all responses)

All tests use in-memory images generated with Pillow — no test files on disk.
Tests share the existing session-scoped test database populated with the
4 FloraMW reference plants (hibiscus, periwinkle, marigold, frangipani).
"""

from __future__ import annotations

import io
import math
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from PIL import Image

from app.identification.catalogue_matching import match_scientific_name
from app.identification.deterministic_provider import DeterministicProvider
from app.identification.exceptions import (
    EmptyUploadError,
    FileTooLargeError,
    ImageDecodingError,
    ImageDimensionError,
    MockProviderForbiddenError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedFormatError,
)
from app.identification.image_validation import validate_and_prepare
from app.identification.provider import (
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
    get_identification_provider,
    normalise_scientific_name,
)
from app.identification.service import (
    _validate_candidate,
    confidence_level,
    run_identification,
)
from app.schemas.identification import (
    ConfidenceLevel,
    IdentificationCandidateOut,
    IdentificationErrorCode,
    IdentificationOutcome,
)


# ---------------------------------------------------------------------------
# Image factory helpers
# ---------------------------------------------------------------------------


def _make_jpeg(width: int = 100, height: int = 80) -> bytes:
    """Generate a valid minimal JPEG in memory."""
    img = Image.new("RGB", (width, height), color=(34, 139, 34))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def _make_png(width: int = 100, height: int = 80) -> bytes:
    """Generate a valid minimal PNG in memory."""
    img = Image.new("RGBA", (width, height), color=(34, 139, 34, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _make_webp(width: int = 100, height: int = 80) -> bytes:
    """Generate a valid minimal WebP in memory."""
    img = Image.new("RGB", (width, height), color=(34, 139, 34))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return buf.getvalue()


def _make_bmp(width: int = 100, height: int = 80) -> bytes:
    """Generate a valid BMP (unsupported format)."""
    img = Image.new("RGB", (width, height), color=(34, 139, 34))
    buf = io.BytesIO()
    img.save(buf, format="BMP")
    return buf.getvalue()


TINY_JPEG = _make_jpeg()
TINY_PNG = _make_png()
TINY_WEBP = _make_webp()


# ===========================================================================
# SECTION 1 — Image validation
# ===========================================================================


class TestImageValidation:
    """Unit tests for validate_and_prepare()."""

    def test_valid_jpeg_returns_payload(self):
        payload = validate_and_prepare(TINY_JPEG, "image/jpeg")
        assert isinstance(payload, ImagePayload)
        assert payload.format == "JPEG"
        assert payload.width_px == 100
        assert payload.height_px == 80
        assert payload.size_bytes > 0
        assert len(payload.content) == payload.size_bytes

    def test_valid_png_returns_payload(self):
        payload = validate_and_prepare(TINY_PNG, "image/png")
        assert payload.format == "PNG"
        assert payload.width_px == 100

    def test_valid_webp_converted_to_jpeg(self):
        """WebP is accepted and converted to JPEG for consistent output."""
        payload = validate_and_prepare(TINY_WEBP, "image/webp")
        assert payload.format == "JPEG"
        assert payload.width_px == 100

    def test_no_declared_content_type_accepted(self):
        """Content-type is optional — format is detected from bytes."""
        payload = validate_and_prepare(TINY_JPEG, None)
        assert payload.format == "JPEG"

    def test_jpeg_content_type_mismatch_accepted_when_actual_matches(self):
        """image/jpg and image/jpeg both map to JPEG — no mismatch error."""
        payload = validate_and_prepare(TINY_JPEG, "image/jpg")
        assert payload.format == "JPEG"

    def test_empty_bytes_raises_empty_upload_error(self):
        with pytest.raises(EmptyUploadError):
            validate_and_prepare(b"", "image/jpeg")

    def test_file_too_large_raises_error(self):
        with patch("app.identification.image_validation.settings") as mock_cfg:
            mock_cfg.MAX_UPLOAD_SIZE_BYTES = 10
            mock_cfg.MAX_IMAGE_DIMENSION_PX = 4096
            with pytest.raises(FileTooLargeError) as exc_info:
                validate_and_prepare(TINY_JPEG, "image/jpeg")
        assert exc_info.value.actual_bytes > 10
        assert exc_info.value.limit_bytes == 10

    def test_unsupported_format_bmp_raises_error(self):
        bmp = _make_bmp()
        with pytest.raises(UnsupportedFormatError) as exc_info:
            validate_and_prepare(bmp, "image/bmp")
        assert exc_info.value.detected_format == "BMP"

    def test_random_bytes_raises_decoding_error(self):
        with pytest.raises(ImageDecodingError):
            validate_and_prepare(b"not an image at all XXXXXXXX", "image/jpeg")

    def test_corrupted_jpeg_raises_decoding_error(self):
        bad = b"\xff\xd8\xff\xe0" + b"\x00" * 200
        with pytest.raises((ImageDecodingError, UnsupportedFormatError)):
            validate_and_prepare(bad, "image/jpeg")

    def test_png_header_only_raises_decoding_error(self):
        bad = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        with pytest.raises((ImageDecodingError, UnsupportedFormatError)):
            validate_and_prepare(bad, "image/png")

    def test_mime_mismatch_png_declared_as_jpeg_raises(self):
        with pytest.raises((UnsupportedFormatError, ImageDecodingError)):
            validate_and_prepare(TINY_PNG, "image/jpeg")

    def test_oversized_image_raises_dimension_error(self):
        large = _make_jpeg(5000, 100)
        with patch("app.identification.image_validation.settings") as mock_cfg:
            mock_cfg.MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
            mock_cfg.MAX_IMAGE_DIMENSION_PX = 4096
            with pytest.raises(ImageDimensionError) as exc_info:
                validate_and_prepare(large, "image/jpeg")
        assert exc_info.value.width == 5000

    def test_image_at_max_dimension_accepted(self):
        edge = _make_jpeg(100, 100)
        with patch("app.identification.image_validation.settings") as mock_cfg:
            mock_cfg.MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024
            mock_cfg.MAX_IMAGE_DIMENSION_PX = 100
            payload = validate_and_prepare(edge, "image/jpeg")
        assert payload.width_px == 100

    def test_output_has_no_exif(self):
        raw = TINY_JPEG
        payload = validate_and_prepare(raw, "image/jpeg")
        output_img = Image.open(io.BytesIO(payload.content))
        exif = output_img.info.get("exif", b"")
        assert exif == b"" or len(exif) == 0


# ===========================================================================
# SECTION 2 — Provider contract and normalisation utilities
# ===========================================================================


class TestNormaliseScientificName:
    """Unit tests for normalise_scientific_name()."""

    def test_basic_binomial(self):
        assert normalise_scientific_name("Hibiscus rosa-sinensis") == "hibiscus rosa-sinensis"

    def test_extra_whitespace_collapsed(self):
        assert normalise_scientific_name("  Hibiscus  rosa-sinensis  ") == "hibiscus rosa-sinensis"

    def test_already_lowercase(self):
        assert normalise_scientific_name("catharanthus roseus") == "catharanthus roseus"

    def test_empty_string(self):
        assert normalise_scientific_name("") == ""

    def test_unicode_nfc(self):
        import unicodedata
        composed = unicodedata.normalize("NFC", "Cr\u00e9pis")
        decomposed = unicodedata.normalize("NFD", "Cr\u00e9pis")
        assert normalise_scientific_name(composed) == normalise_scientific_name(decomposed)


class TestProviderContract:
    """Tests for ProviderCandidate and ProviderResult dataclasses."""

    def test_candidate_defaults(self):
        c = ProviderCandidate(scientific_name="Test species", confidence=0.5)
        assert c.common_names == []
        assert c.family is None
        assert c.notes is None

    def test_result_defaults(self):
        r = ProviderResult(candidates=[], provider_id="test-provider")
        assert r.model_version is None
        assert r.provider_meta == {}

    def test_image_payload_attributes(self):
        p = ImagePayload(
            content=b"data",
            format="JPEG",
            width_px=100,
            height_px=80,
            size_bytes=4,
        )
        assert p.format == "JPEG"
        assert p.width_px == 100


# ===========================================================================
# SECTION 3 — Deterministic provider & Configuration Safety
# ===========================================================================


class TestDeterministicProvider:
    """Tests for the DeterministicProvider and environment controls."""

    @pytest.mark.asyncio
    async def test_returns_catalogue_candidates(self):
        provider = DeterministicProvider()
        payload = ImagePayload(
            content=TINY_JPEG,
            format="JPEG",
            width_px=100,
            height_px=80,
            size_bytes=len(TINY_JPEG),
        )
        result = await provider.identify(payload)
        assert isinstance(result, ProviderResult)
        assert len(result.candidates) == 3
        assert result.provider_id == "floramw-deterministic-v1"

    @pytest.mark.asyncio
    async def test_candidates_have_valid_confidence(self):
        provider = DeterministicProvider()
        payload = ImagePayload(
            content=TINY_JPEG,
            format="JPEG",
            width_px=100,
            height_px=80,
            size_bytes=len(TINY_JPEG),
        )
        result = await provider.identify(payload)
        for c in result.candidates:
            assert 0.0 <= c.confidence <= 1.0
            assert math.isfinite(c.confidence)
            assert c.scientific_name

    @pytest.mark.asyncio
    async def test_forbidden_in_production(self):
        provider = DeterministicProvider()
        payload = ImagePayload(
            content=TINY_JPEG,
            format="JPEG",
            width_px=100,
            height_px=80,
            size_bytes=len(TINY_JPEG),
        )
        with patch("app.identification.deterministic_provider.settings") as mock_cfg:
            mock_cfg.ENVIRONMENT = "production"
            mock_cfg.ALLOW_MOCK_PROVIDER = True
            with pytest.raises(MockProviderForbiddenError):
                await provider.identify(payload)

    @pytest.mark.asyncio
    async def test_forbidden_when_allow_mock_is_false(self):
        provider = DeterministicProvider()
        payload = ImagePayload(
            content=TINY_JPEG,
            format="JPEG",
            width_px=100,
            height_px=80,
            size_bytes=len(TINY_JPEG),
        )
        with patch("app.identification.deterministic_provider.settings") as mock_cfg:
            mock_cfg.ENVIRONMENT = "development"
            mock_cfg.ALLOW_MOCK_PROVIDER = False
            with pytest.raises(MockProviderForbiddenError):
                await provider.identify(payload)

    @pytest.mark.asyncio
    async def test_result_contains_known_floramw_species(self):
        provider = DeterministicProvider()
        payload = ImagePayload(
            content=TINY_JPEG,
            format="JPEG",
            width_px=100,
            height_px=80,
            size_bytes=len(TINY_JPEG),
        )
        result = await provider.identify(payload)
        scientific_names = {c.scientific_name for c in result.candidates}
        expected = {
            "Hibiscus rosa-sinensis",
            "Catharanthus roseus",
            "Tagetes erecta",
        }
        assert scientific_names == expected


class TestProviderConfiguration:
    """Tests for get_identification_provider() factory."""

    def test_deterministic_provider_resolved_in_dev_when_allowed(self):
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "development"
            s.IDENTIFICATION_PROVIDER = "deterministic"
            s.ALLOW_MOCK_PROVIDER = True
            p = get_identification_provider()
            assert p.provider_id == "floramw-deterministic-v1"

    def test_mock_provider_forbidden_in_production(self):
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "production"
            s.IDENTIFICATION_PROVIDER = "deterministic"
            s.ALLOW_MOCK_PROVIDER = True
            with pytest.raises(MockProviderForbiddenError):
                get_identification_provider()

    def test_mock_provider_forbidden_when_allow_mock_is_false(self):
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "development"
            s.IDENTIFICATION_PROVIDER = "deterministic"
            s.ALLOW_MOCK_PROVIDER = False
            with pytest.raises(MockProviderForbiddenError):
                get_identification_provider()

    def test_disabled_provider_raises_unavailable(self):
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "development"
            s.IDENTIFICATION_PROVIDER = "disabled"
            s.ALLOW_MOCK_PROVIDER = True
            with pytest.raises(ProviderUnavailableError):
                get_identification_provider()

    def test_unknown_provider_raises_unavailable(self):
        with patch("app.core.config.settings") as s:
            s.ENVIRONMENT = "development"
            s.IDENTIFICATION_PROVIDER = "unknown_ai_vendor"
            s.ALLOW_MOCK_PROVIDER = True
            with pytest.raises(ProviderUnavailableError):
                get_identification_provider()


# ===========================================================================
# SECTION 4 — Confidence level & Candidate validation
# ===========================================================================


class TestConfidenceAndValidation:
    """Tests for confidence band assignment and candidate validation."""

    def test_confidence_bands(self):
        with patch("app.identification.service.settings") as m:
            m.CONFIDENCE_THRESHOLD_HIGH = 0.70
            m.CONFIDENCE_THRESHOLD_MODERATE = 0.45
            m.CONFIDENCE_THRESHOLD_LOW = 0.20
            assert confidence_level(0.90) == ConfidenceLevel.HIGH
            assert confidence_level(0.70) == ConfidenceLevel.HIGH
            assert confidence_level(0.60) == ConfidenceLevel.MODERATE
            assert confidence_level(0.45) == ConfidenceLevel.MODERATE
            assert confidence_level(0.30) == ConfidenceLevel.LOW
            assert confidence_level(0.20) == ConfidenceLevel.LOW
            assert confidence_level(0.10) == ConfidenceLevel.UNCERTAIN
            assert confidence_level(0.0) == ConfidenceLevel.UNCERTAIN

    def test_validate_candidate_rejects_nan(self):
        c = ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=float("nan"))
        assert _validate_candidate(c) is None

    def test_validate_candidate_rejects_positive_infinity(self):
        c = ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=float("inf"))
        assert _validate_candidate(c) is None

    def test_validate_candidate_rejects_negative_infinity(self):
        c = ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=float("-inf"))
        assert _validate_candidate(c) is None

    def test_validate_candidate_rejects_out_of_range(self):
        c_high = ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=1.01)
        c_low = ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=-0.01)
        assert _validate_candidate(c_high) is None
        assert _validate_candidate(c_low) is None

    def test_validate_candidate_rejects_empty_name(self):
        c_empty = ProviderCandidate(scientific_name="", confidence=0.8)
        c_spaces = ProviderCandidate(scientific_name="   ", confidence=0.8)
        assert _validate_candidate(c_empty) is None
        assert _validate_candidate(c_spaces) is None

    def test_candidate_schema_rejects_nan(self):
        with pytest.raises(pydantic.ValidationError):
            IdentificationCandidateOut(
                scientific_name="Hibiscus rosa-sinensis",
                confidence=float("nan"),
                confidence_level=ConfidenceLevel.HIGH,
                catalogue_matched=True,
            )

    def test_candidate_schema_rejects_inf(self):
        with pytest.raises(pydantic.ValidationError):
            IdentificationCandidateOut(
                scientific_name="Hibiscus rosa-sinensis",
                confidence=float("inf"),
                confidence_level=ConfidenceLevel.HIGH,
                catalogue_matched=True,
            )


# ===========================================================================
# SECTION 5 — Catalogue matching
# ===========================================================================


class TestCatalogueMatching:
    """Tests for match_scientific_name() against the seeded test database."""

    @pytest.mark.asyncio
    async def test_known_species_matches(self, db_session):
        result = await match_scientific_name("Hibiscus rosa-sinensis", db_session)
        assert result.matched is True
        assert result.plant_id == "hibiscus"
        assert result.catalogue_name == "Chinese hibiscus"

    @pytest.mark.asyncio
    async def test_case_insensitive_match(self, db_session):
        result = await match_scientific_name("hibiscus ROSA-SINENSIS", db_session)
        assert result.matched is True
        assert result.plant_id == "hibiscus"

    @pytest.mark.asyncio
    async def test_whitespace_normalised_match(self, db_session):
        result = await match_scientific_name("  Hibiscus  rosa-sinensis  ", db_session)
        assert result.matched is True

    @pytest.mark.asyncio
    async def test_all_four_catalogue_plants_match(self, db_session):
        pairs = [
            ("Hibiscus rosa-sinensis", "hibiscus"),
            ("Catharanthus roseus", "periwinkle"),
            ("Tagetes erecta", "marigold"),
            ("Plumeria rubra", "frangipani"),
        ]
        for scientific, expected_id in pairs:
            result = await match_scientific_name(scientific, db_session)
            assert result.matched is True, f"Expected match for {scientific}"
            assert result.plant_id == expected_id

    @pytest.mark.asyncio
    async def test_unknown_species_returns_no_match(self, db_session):
        result = await match_scientific_name("Completely unknown species", db_session)
        assert result.matched is False
        assert result.plant_id is None

    @pytest.mark.asyncio
    async def test_empty_name_returns_no_match(self, db_session):
        result = await match_scientific_name("", db_session)
        assert result.matched is False

    @pytest.mark.asyncio
    async def test_partial_name_does_not_match(self, db_session):
        result = await match_scientific_name("Hibiscus", db_session)
        assert result.matched is False


# ===========================================================================
# SECTION 6 — Identification service
# ===========================================================================


def _make_provider_with_candidates(
    candidates: list[ProviderCandidate],
    provider_id: str = "floramw-deterministic-v1",
) -> MagicMock:
    """Build a mock provider that returns specific candidates."""
    provider = MagicMock()
    provider.provider_id = provider_id
    provider.identify = AsyncMock(
        return_value=ProviderResult(
            candidates=candidates,
            provider_id=provider_id,
            model_version="mock-v1",
        )
    )
    return provider


def _make_failing_provider(exception: Exception) -> MagicMock:
    """Build a mock provider that raises a specific exception."""
    provider = MagicMock()
    provider.provider_id = "floramw-deterministic-v1"
    provider.identify = AsyncMock(side_effect=exception)
    return provider


class TestIdentificationService:
    """Unit tests for run_identification()."""

    @pytest.mark.asyncio
    async def test_valid_image_deterministic_returns_candidates(self, db_session):
        provider = DeterministicProvider()
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert response.outcome == IdentificationOutcome.DEMO_MODE
        assert len(response.candidates) == 3
        assert response.safety_disclaimer
        assert response.provider.is_demo is True

    @pytest.mark.asyncio
    async def test_catalogue_matched_candidates_have_plant_id(self, db_session):
        provider = DeterministicProvider()
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        hibiscus = next(
            (c for c in response.candidates if "Hibiscus" in c.scientific_name),
            None,
        )
        assert hibiscus is not None
        assert hibiscus.catalogue_matched is True
        assert hibiscus.catalogue_plant_id == "hibiscus"

    @pytest.mark.asyncio
    async def test_unmatched_external_species_preserved(self, db_session):
        candidates = [
            ProviderCandidate(
                scientific_name="Rosa canina",
                confidence=0.85,
                common_names=["Dog rose"],
            )
        ]
        provider = _make_provider_with_candidates(candidates)
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert len(response.candidates) == 1
        assert response.candidates[0].catalogue_matched is False
        assert response.candidates[0].catalogue_plant_id is None
        assert response.candidates[0].scientific_name == "Rosa canina"

    @pytest.mark.asyncio
    async def test_multiple_candidates_sorted_by_confidence(self, db_session):
        candidates = [
            ProviderCandidate(scientific_name="Tagetes erecta", confidence=0.38),
            ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=0.72),
            ProviderCandidate(scientific_name="Catharanthus roseus", confidence=0.55),
        ]
        provider = _make_provider_with_candidates(candidates)
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        scores = [c.confidence for c in response.candidates]
        assert scores == sorted(scores, reverse=True)

    @pytest.mark.asyncio
    async def test_low_confidence_adds_photo_guidance(self, db_session):
        candidates = [
            ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=0.15)
        ]
        provider = _make_provider_with_candidates(candidates)
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert response.photo_guidance is not None
        assert len(response.photo_guidance.suggested_actions) > 0

    @pytest.mark.asyncio
    async def test_high_confidence_no_guidance(self, db_session):
        candidates = [
            ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=0.90)
        ]
        provider = _make_provider_with_candidates(candidates)
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert response.photo_guidance is None

    @pytest.mark.asyncio
    async def test_no_candidates_returns_no_match(self, db_session):
        provider = _make_provider_with_candidates([])
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert response.outcome == IdentificationOutcome.NO_MATCH
        assert response.candidates == []
        assert response.photo_guidance is not None

    @pytest.mark.asyncio
    async def test_client_request_id_passthrough(self, db_session):
        provider = DeterministicProvider()
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
            client_request_id="req-test-uuid-1234",
        )
        assert response.client_request_id == "req-test-uuid-1234"

    @pytest.mark.asyncio
    async def test_empty_upload_raises_http_400(self, db_session):
        provider = DeterministicProvider()
        with pytest.raises(HTTPException) as exc_info:
            await run_identification(
                raw_bytes=b"",
                declared_content_type="image/jpeg",
                provider=provider,
                db=db_session,
            )
        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert detail["error_code"] == IdentificationErrorCode.IMAGE_EMPTY
        assert detail["retryable"] is False
        assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_provider_unavailable_raises_http_503(self, db_session):
        provider = _make_failing_provider(ProviderUnavailableError("offline"))
        with pytest.raises(HTTPException) as exc_info:
            await run_identification(
                raw_bytes=TINY_JPEG,
                declared_content_type="image/jpeg",
                provider=provider,
                db=db_session,
            )
        assert exc_info.value.status_code == 503
        detail = exc_info.value.detail
        assert detail["error_code"] == IdentificationErrorCode.PROVIDER_UNAVAILABLE
        assert detail["retryable"] is True
        assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_provider_timeout_raises_http_504(self, db_session):
        provider = _make_failing_provider(ProviderTimeoutError("timeout"))
        with pytest.raises(HTTPException) as exc_info:
            await run_identification(
                raw_bytes=TINY_JPEG,
                declared_content_type="image/jpeg",
                provider=provider,
                db=db_session,
            )
        assert exc_info.value.status_code == 504
        detail = exc_info.value.detail
        assert detail["error_code"] == IdentificationErrorCode.PROVIDER_TIMEOUT
        assert detail["retryable"] is True
        assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_provider_response_error_raises_http_502(self, db_session):
        provider = _make_failing_provider(ProviderResponseError("bad response"))
        with pytest.raises(HTTPException) as exc_info:
            await run_identification(
                raw_bytes=TINY_JPEG,
                declared_content_type="image/jpeg",
                provider=provider,
                db=db_session,
            )
        assert exc_info.value.status_code == 502
        detail = exc_info.value.detail
        assert detail["error_code"] == IdentificationErrorCode.PROVIDER_ERROR
        assert detail["retryable"] is False
        assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_candidate_with_empty_name_discarded(self, db_session):
        candidates = [
            ProviderCandidate(scientific_name="", confidence=0.9),
            ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=0.72),
        ]
        provider = _make_provider_with_candidates(candidates)
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert len(response.candidates) == 1
        assert response.candidates[0].scientific_name == "Hibiscus rosa-sinensis"

    @pytest.mark.asyncio
    async def test_candidate_with_invalid_confidence_discarded(self, db_session):
        candidates = [
            ProviderCandidate(scientific_name="Bad plant", confidence=1.5),
            ProviderCandidate(scientific_name="Hibiscus rosa-sinensis", confidence=0.72),
        ]
        provider = _make_provider_with_candidates(candidates)
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert len(response.candidates) == 1

    @pytest.mark.asyncio
    async def test_safety_disclaimer_always_present_in_response(self, db_session):
        provider = DeterministicProvider()
        response = await run_identification(
            raw_bytes=TINY_JPEG,
            declared_content_type="image/jpeg",
            provider=provider,
            db=db_session,
        )
        assert response.safety_disclaimer
        assert len(response.safety_disclaimer) > 50

    @pytest.mark.asyncio
    async def test_internal_errors_not_leaked(self, db_session):
        """Unexpected provider exceptions must not expose internal paths."""
        provider = _make_failing_provider(RuntimeError("secret internal path /etc/passwd"))
        with pytest.raises(HTTPException) as exc_info:
            await run_identification(
                raw_bytes=TINY_JPEG,
                declared_content_type="image/jpeg",
                provider=provider,
                db=db_session,
            )
        assert exc_info.value.status_code == 502
        detail = exc_info.value.detail
        assert "/etc/passwd" not in detail["message"]
        assert "secret" not in detail["message"]


# ===========================================================================
# SECTION 7 — API endpoint integration tests
# ===========================================================================


class TestIdentificationEndpoint:
    """Integration tests for POST /api/v1/identifications."""

    @pytest.mark.asyncio
    async def test_valid_jpeg_returns_200(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_valid_png_returns_200(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.png", TINY_PNG, "image/png")},
        )
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_response_has_required_fields(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "outcome" in data
        assert "candidates" in data
        assert "safety_disclaimer" in data
        assert "provider" in data
        assert "created_at" in data
        assert "client_request_id" in data

    @pytest.mark.asyncio
    async def test_response_outcome_is_demo_mode(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["outcome"] == "demo_mode"

    @pytest.mark.asyncio
    async def test_provider_is_demo_flagged(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["provider"]["is_demo"] is True

    @pytest.mark.asyncio
    async def test_candidates_have_correct_structure(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["candidates"]) == 3
        for candidate in data["candidates"]:
            assert "scientific_name" in candidate
            assert "confidence" in candidate
            assert "confidence_level" in candidate
            assert "catalogue_matched" in candidate
            assert 0.0 <= candidate["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_catalogue_matched_candidates_have_plant_ids(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        for c in data["candidates"]:
            assert c["catalogue_matched"] is True
            assert c["catalogue_plant_id"] is not None

    @pytest.mark.asyncio
    async def test_x_client_request_id_header_echoed(self, client: AsyncClient):
        req_id = "req-123e4567-e89b-12d3-a456-426614174000"
        response = await client.post(
            "/api/v1/identifications",
            headers={"X-Client-Request-Id": req_id},
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["client_request_id"] == req_id

    @pytest.mark.asyncio
    async def test_x_client_request_id_too_long_returns_400(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            headers={"X-Client-Request-Id": "x" * 65},
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "64 characters" in detail["message"]

    @pytest.mark.asyncio
    async def test_empty_file_returns_400(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("empty.jpg", b"", "image/jpeg")},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.IMAGE_EMPTY
        assert detail["retryable"] is False
        assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_unsupported_format_returns_415(self, client: AsyncClient):
        bmp = _make_bmp()
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.bmp", bmp, "image/bmp")},
        )
        assert response.status_code == 415
        detail = response.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.IMAGE_FORMAT_UNSUPPORTED
        assert detail["retryable"] is False
        assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_random_bytes_returns_400(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("bad.jpg", b"this is not an image", "image/jpeg")},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.IMAGE_DECODING_FAILED
        assert detail["retryable"] is False

    @pytest.mark.asyncio
    async def test_missing_image_field_returns_422(self, client: AsyncClient):
        response = await client.post("/api/v1/identifications")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_production_environment_blocks_mock_with_503(self, client: AsyncClient):
        with patch("app.core.config.settings.ENVIRONMENT", "production"):
            response = await client.post(
                "/api/v1/identifications",
                files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
            )
            assert response.status_code == 503
            detail = response.json()["detail"]
            assert detail["error_code"] == IdentificationErrorCode.IDENTIFICATION_DISABLED
            assert detail["retryable"] is False
            assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_unconfigured_provider_returns_503(self, client: AsyncClient):
        with patch("app.core.config.settings.IDENTIFICATION_PROVIDER", "disabled"):
            response = await client.post(
                "/api/v1/identifications",
                files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
            )
            assert response.status_code == 503
            detail = response.json()["detail"]
            assert detail["error_code"] == IdentificationErrorCode.PROVIDER_UNAVAILABLE
            assert detail["retryable"] is True
            assert "safety_disclaimer" in detail

    @pytest.mark.asyncio
    async def test_provider_timeout_returns_504(self, client: AsyncClient):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        failing_provider = _make_failing_provider(ProviderTimeoutError("timeout"))
        app.dependency_overrides[get_current_provider] = lambda: failing_provider
        try:
            response = await client.post(
                "/api/v1/identifications",
                files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
            )
            assert response.status_code == 504
            detail = response.json()["detail"]
            assert detail["error_code"] == IdentificationErrorCode.PROVIDER_TIMEOUT
            assert detail["retryable"] is True
            assert "safety_disclaimer" in detail
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

    @pytest.mark.asyncio
    async def test_provider_error_returns_502(self, client: AsyncClient):
        from app.api.v1.identifications import get_current_provider
        from app.main import app

        failing_provider = _make_failing_provider(ProviderResponseError("bad payload"))
        app.dependency_overrides[get_current_provider] = lambda: failing_provider
        try:
            response = await client.post(
                "/api/v1/identifications",
                files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
            )
            assert response.status_code == 502
            detail = response.json()["detail"]
            assert detail["error_code"] == IdentificationErrorCode.PROVIDER_ERROR
            assert detail["retryable"] is False
            assert "safety_disclaimer" in detail
        finally:
            app.dependency_overrides.pop(get_current_provider, None)

    @pytest.mark.asyncio
    async def test_no_internal_paths_in_response(self, client: AsyncClient):
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("plant.jpg", TINY_JPEG, "image/jpeg")},
        )
        raw_text = response.text
        assert "Traceback" not in raw_text
        assert "C:\\" not in raw_text
        assert "floramw.db" not in raw_text

    @pytest.mark.asyncio
    async def test_existing_plant_endpoints_still_work(self, client: AsyncClient):
        r = await client.get("/api/v1/plants")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 4

    @pytest.mark.asyncio
    async def test_existing_districts_endpoint_still_works(self, client: AsyncClient):
        r = await client.get("/api/v1/districts")
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_health_endpoint_still_works(self, client: AsyncClient):
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"
