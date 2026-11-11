"""Identification-specific exception hierarchy for FloraMW.

Separates provider failures, image validation errors, and service-level
errors so that the API layer can map each to an appropriate HTTP response
without exposing implementation details.

HTTP mapping (enforced in the API route, not here):
  EmptyUploadError         → 400 Bad Request
  ImageDecodingError       → 400 Bad Request
  FileTooLargeError        → 413 Content Too Large
  UnsupportedFormatError   → 415 Unsupported Media Type
  ImageDimensionError      → 422 Unprocessable Entity
  ProviderUnavailableError → 503 Service Unavailable
  ProviderTimeoutError     → 504 Gateway Timeout
  ProviderResponseError    → 502 Bad Gateway
  MockProviderForbiddenError → 503 Service Unavailable (config error)
"""

import http


class IdentificationError(Exception):
    """Base class for all identification subsystem errors."""

    retryable: bool = False
    http_status: int = 500


# ---------------------------------------------------------------------------
# Image validation errors — non-retryable; fix the input
# ---------------------------------------------------------------------------


class ImageValidationError(IdentificationError):
    """Raised when the uploaded image fails structural or content validation.

    Non-retryable: the caller must supply a different or corrected image.
    """

    retryable: bool = False


class EmptyUploadError(ImageValidationError):
    """Raised when the uploaded file has zero bytes.

    HTTP 400 Bad Request.
    """

    http_status: int = 400


class FileTooLargeError(ImageValidationError):
    """Raised when the uploaded file exceeds the configured size limit.

    HTTP 413 Content Too Large.
    """

    http_status: int = 413

    def __init__(self, actual_bytes: int, limit_bytes: int) -> None:
        super().__init__(
            f"Upload size {actual_bytes:,} bytes exceeds the {limit_bytes // (1024 * 1024)} MB limit."
        )
        self.actual_bytes = actual_bytes
        self.limit_bytes = limit_bytes


class UnsupportedFormatError(ImageValidationError):
    """Raised when the image format is not supported or the declared MIME type
    is inconsistent with the actual file content.

    HTTP 415 Unsupported Media Type.
    """

    http_status: int = 415

    def __init__(self, detected_format: str | None) -> None:
        label = detected_format or "unknown"
        super().__init__(
            f"Image format '{label}' is not supported. Upload a JPEG or PNG photograph."
        )
        self.detected_format = detected_format


class ImageDecodingError(ImageValidationError):
    """Raised when the image cannot be decoded (truncated or corrupted file).

    HTTP 400 Bad Request.
    """

    http_status: int = 400


class ImageDimensionError(ImageValidationError):
    """Raised when image pixel dimensions exceed configured limits.

    HTTP 422 Unprocessable Entity — the file is a valid image but cannot be
    processed at its current dimensions.
    """

    http_status: int = 422

    def __init__(self, width: int, height: int, max_dim: int) -> None:
        super().__init__(
            f"Image dimensions {width}×{height} px exceed the maximum allowed "
            f"dimension of {max_dim} px per side."
        )
        self.width = width
        self.height = height
        self.max_dim = max_dim


# ---------------------------------------------------------------------------
# Provider errors — may be retryable
# ---------------------------------------------------------------------------


class ProviderError(IdentificationError):
    """Base class for identification provider errors."""


class ProviderUnavailableError(ProviderError):
    """Raised when no provider is configured or the provider is not reachable.

    Retryable. HTTP 503 Service Unavailable.
    """

    retryable: bool = True
    http_status: int = 503


class ProviderTimeoutError(ProviderError):
    """Raised when the provider does not respond within the configured timeout.

    Retryable. HTTP 504 Gateway Timeout.
    """

    retryable: bool = True
    http_status: int = 504


class ProviderResponseError(ProviderError):
    """Raised when the provider returns a malformed or unprocessable response.

    Non-retryable: indicates a provider contract violation. HTTP 502 Bad Gateway.
    """

    retryable: bool = False
    http_status: int = 502


class MockProviderForbiddenError(ProviderError):
    """Raised when the deterministic test provider is invoked in production.

    Non-retryable. HTTP 503 Service Unavailable (configuration error).
    """

    retryable: bool = False
    http_status: int = 503


class ConfigurationError(IdentificationError):
    """Raised when a provider is misconfigured.

    Non-retryable. HTTP 503 Service Unavailable (configuration error).
    """

    retryable: bool = False
    http_status: int = 503


class ProviderNetworkError(ProviderError):
    """Raised when a network-level error prevents reaching the provider.

    Retryable. HTTP 503 Service Unavailable.
    """

    retryable: bool = True
    http_status: int = 503


class IdempotencyConflictError(IdentificationError):
    """Raised when a client_request_id was used with a different image payload.

    Non-retryable. HTTP 409 Conflict.
    """

    retryable: bool = False
    http_status: int = 409


class RequestStillProcessingError(IdentificationError):
    """Raised when a duplicate request is received while still processing.

    Retryable. HTTP 202 Accepted.
    """

    retryable: bool = True
    http_status: int = 202
