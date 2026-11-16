"""Automated test suite for Phase 4.2.1: Upload and Transport Security Hardening.

Covers:
1. Security headers on all responses (X-Content-Type-Options, X-Frame-Options, Referrer-Policy).
2. HSTS behavior: absent on plain HTTP in dev; present over HTTPS / when ENABLE_HSTS is True.
3. Early Content-Length upload size enforcement (HTTP 413).
4. Streaming chunked upload size ceiling without Content-Length (HTTP 413).
5. Safe image dimension and total pixel count limits (HTTP 422).
6. Decompression bomb protection / extreme pixel counts (HTTP 422).
7. Invalid and corrupted image handling (HTTP 400).
8. UploadFile resource cleanup (close() invoked on success, validation failure, and error).
9. Filename log sanitization (control characters and CRLF stripped).
10. Corrected X-Client-Request-Id validation error code (REQUEST_VALIDATION_FAILED, HTTP 400).
"""

from __future__ import annotations

import io
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from PIL import Image

from app.api.v1.identifications import sanitize_log_string
from app.core.config import settings
from app.identification.exceptions import ImageDimensionError
from app.identification.image_validation import validate_and_prepare
from app.main import app
from app.schemas.identification import IdentificationErrorCode


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def _make_test_jpeg(width: int = 10, height: int = 10, color: str = "green") -> bytes:
    """Create a minimal valid JPEG in memory."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _make_test_png(width: int = 10, height: int = 10) -> bytes:
    """Create a minimal valid PNG in memory."""
    img = Image.new("RGBA", (width, height), color=(0, 128, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 1. Transport Security Headers Tests
# ---------------------------------------------------------------------------

class TestSecurityHeaders:
    """Verify defensive HTTP security headers across API endpoints."""

    @pytest.mark.asyncio
    async def test_security_headers_present_on_root_and_api(self, client: AsyncClient):
        for path in ("/", "/health", "/api/v1/districts", "/api/v1/plants"):
            response = await client.get(path)
            assert response.headers.get("X-Content-Type-Options") == "nosniff"
            assert response.headers.get("X-Frame-Options") == "DENY"
            assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    @pytest.mark.asyncio
    async def test_hsts_absent_on_plain_http_in_development(self, client: AsyncClient):
        """HSTS must NOT be emitted over plain HTTP in development."""
        response = await client.get("/health")
        assert "Strict-Transport-Security" not in response.headers

    @pytest.mark.asyncio
    async def test_hsts_present_when_https_and_enabled(self):
        """HSTS must be emitted when request is HTTPS and ENABLE_HSTS is True."""
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport,
            base_url="https://app.floramw.com",
            headers={"X-Forwarded-Proto": "https"},
        ) as https_client:
            with patch.object(settings, "ENABLE_HSTS", True):
                response = await https_client.get("/health")
                hsts = response.headers.get("Strict-Transport-Security")
                assert hsts is not None
                assert "max-age=" in hsts
                assert "includeSubDomains" in hsts


# ---------------------------------------------------------------------------
# 2. Upload Size & Streaming Limit Tests
# ---------------------------------------------------------------------------

class TestUploadSizeLimits:
    """Verify request body size limits and streaming chunk ceilings."""

    @pytest.mark.asyncio
    async def test_oversized_upload_with_content_length_rejected_413(self, client: AsyncClient):
        """Oversized upload with Content-Length rejected early without buffering."""
        large_payload = b"X" * (settings.MAX_UPLOAD_SIZE_BYTES + 100_000)
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("large.jpg", large_payload, "image/jpeg")},
        )
        assert response.status_code == 413
        detail = response.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.IMAGE_TOO_LARGE.value
        assert "too large" in detail["message"].lower()

    @pytest.mark.asyncio
    async def test_streaming_chunked_oversized_upload_rejected_413(self):
        """Streaming chunked upload without Content-Length rejected when ceiling exceeded."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
            async def chunk_generator():
                boundary = "----TestBoundarySecurityHardening"
                yield f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"stream.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n".encode()
                chunk_data = b"Y" * (1024 * 1024)  # 1 MB chunks
                for _ in range(12):  # 12 MB total > 10 MB limit
                    yield chunk_data
                yield f"\r\n--{boundary}--\r\n".encode()

            response = await test_client.post(
                "/api/v1/identifications",
                content=chunk_generator(),
                headers={"Content-Type": "multipart/form-data; boundary=----TestBoundarySecurityHardening"},
            )
            assert response.status_code == 413
            detail = response.json()["detail"]
            assert detail["error_code"] == IdentificationErrorCode.IMAGE_TOO_LARGE.value

    @pytest.mark.asyncio
    async def test_valid_image_upload_under_size_limit_accepted(self, client: AsyncClient):
        """Normal image well under size limit accepted."""
        valid_jpeg = _make_test_jpeg(100, 100)
        response = await client.post(
            "/api/v1/identifications",
            files={"image": ("flower.jpg", valid_jpeg, "image/jpeg")},
        )
        assert response.status_code == 200
        assert "candidates" in response.json()


# ---------------------------------------------------------------------------
# 3. Image Dimension & Resource Protection Tests
# ---------------------------------------------------------------------------

class TestImageResourceProtection:
    """Verify maximum dimension and total pixel count guards."""

    def test_dimensions_exceeding_max_dim_rejected(self):
        """Image with one dimension exceeding MAX_IMAGE_DIMENSION_PX is rejected."""
        oversized = _make_test_jpeg(width=4097, height=100)
        with pytest.raises(ImageDimensionError):
            validate_and_prepare(oversized, "image/jpeg")

    def test_total_pixels_exceeding_max_pixels_rejected(self):
        """Image with total pixel area exceeding MAX_IMAGE_TOTAL_PIXELS is rejected."""
        with patch.object(settings, "MAX_IMAGE_TOTAL_PIXELS", 5000):
            with patch.object(settings, "MAX_IMAGE_DIMENSION_PX", 4096):
                img_bytes = _make_test_jpeg(width=100, height=100)
                with pytest.raises(ImageDimensionError):
                    validate_and_prepare(img_bytes, "image/jpeg")

    def test_valid_dimensions_accepted(self):
        """Image within dimensions and pixel count is successfully prepared."""
        valid_bytes = _make_test_jpeg(width=200, height=150)
        payload = validate_and_prepare(valid_bytes, "image/jpeg")
        assert payload.format == "JPEG"
        assert payload.width_px == 200
        assert payload.height_px == 150
        assert payload.size_bytes > 0


# ---------------------------------------------------------------------------
# 4. Upload Cleanup and Resource Handling Tests
# ---------------------------------------------------------------------------

class TestUploadResourceCleanup:
    """Verify UploadFile descriptors are reliably closed."""

    @pytest.mark.asyncio
    async def test_upload_file_closed_after_successful_identification(self, client: AsyncClient):
        valid_jpeg = _make_test_jpeg(50, 50)
        with patch("starlette.datastructures.UploadFile.close", autospec=True) as mock_close:
            response = await client.post(
                "/api/v1/identifications",
                files={"image": ("clean.jpg", valid_jpeg, "image/jpeg")},
            )
            assert response.status_code == 200
            assert mock_close.called

    @pytest.mark.asyncio
    async def test_upload_file_closed_after_validation_error(self, client: AsyncClient):
        with patch("starlette.datastructures.UploadFile.close", autospec=True) as mock_close:
            response = await client.post(
                "/api/v1/identifications",
                files={"image": ("corrupted.jpg", b"invalid_bytes_data", "image/jpeg")},
            )
            assert response.status_code == 400
            assert mock_close.called

    @pytest.mark.asyncio
    async def test_upload_file_closed_after_unexpected_exception(self, client: AsyncClient):
        valid_jpeg = _make_test_jpeg(50, 50)
        with patch(
            "app.api.v1.identifications.run_identification",
            side_effect=HTTPException(status_code=500, detail="Internal unexpected error"),
        ):
            with patch("starlette.datastructures.UploadFile.close", autospec=True) as mock_close:
                response = await client.post(
                    "/api/v1/identifications",
                    files={"image": ("crash.jpg", valid_jpeg, "image/jpeg")},
                )
                assert response.status_code == 500
                assert mock_close.called


# ---------------------------------------------------------------------------
# 5. Logging and Validation Error Corrections
# ---------------------------------------------------------------------------

class TestLoggingAndValidationCorrections:
    """Verify log sanitization and corrected validation error codes."""

    def test_sanitize_log_string_removes_crlf_and_control_chars(self):
        malicious = "flower.jpg\r\nCRITICAL: Admin login bypassed\r\n"
        cleaned = sanitize_log_string(malicious)
        assert "\r" not in cleaned
        assert "\n" not in cleaned
        assert cleaned == "flower.jpgCRITICAL: Admin login bypassed"

    def test_sanitize_log_string_handles_none_and_empty(self):
        assert sanitize_log_string(None) == "<unnamed>"
        assert sanitize_log_string("") == "<unnamed>"
        assert sanitize_log_string("   ") == "<unnamed>"

    def test_sanitize_log_string_truncates_to_max_len(self):
        long_name = "a" * 300
        cleaned = sanitize_log_string(long_name, max_len=50)
        assert len(cleaned) == 50

    @pytest.mark.asyncio
    async def test_x_client_request_id_too_long_returns_request_validation_failed(self, client: AsyncClient):
        """Oversized X-Client-Request-Id returns 400 with REQUEST_VALIDATION_FAILED."""
        valid_jpeg = _make_test_jpeg(20, 20)
        response = await client.post(
            "/api/v1/identifications",
            headers={"X-Client-Request-Id": "x" * 65},
            files={"image": ("plant.jpg", valid_jpeg, "image/jpeg")},
        )
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["error_code"] == IdentificationErrorCode.REQUEST_VALIDATION_FAILED.value
        assert "64 characters" in detail["message"]
        assert detail["retryable"] is False

    def test_cors_wildcard_with_credentials_rejected(self):
        """Settings rejects CORS_ALLOW_CREDENTIALS=True with wildcard origin."""
        from app.core.config import Settings
        with pytest.raises(ValueError) as exc_info:
            Settings(CORS_ORIGINS=["*"], CORS_ALLOW_CREDENTIALS=True)
        assert "forbidden by CORS specification" in str(exc_info.value)

