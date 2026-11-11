"""Botanical identification application service.

Coordinates the full identification workflow:
1. Image validation and preparation (image_validation layer)
2. Provider invocation (IdentificationProvider)
3. Candidate confidence interpretation and finite-value validation
4. Catalogue matching (catalogue_matching layer)
5. Structured response construction

Error handling policy (raises HTTPException with appropriate status):
  EmptyUploadError         → HTTP 400
  ImageDecodingError       → HTTP 400
  FileTooLargeError        → HTTP 413
  UnsupportedFormatError   → HTTP 415
  ImageDimensionError      → HTTP 422
  MockProviderForbiddenError → HTTP 503 (identification disabled in env)
  ProviderUnavailableError → HTTP 503 (temporary; retryable)
  ProviderTimeoutError     → HTTP 504 (temporary; retryable)
  ProviderResponseError    → HTTP 502
  Unexpected Exception     → HTTP 502

HTTP 200 is returned only when the image is valid and the provider completes
(even if it finds no candidates — that is a legitimate result, not an error).

No internal state, secrets, or stack traces are included in returned schemas
or exception details.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.identification.catalogue_matching import match_scientific_name
from app.identification.exceptions import (
    EmptyUploadError,
    FileTooLargeError,
    ImageDecodingError,
    ImageDimensionError,
    ImageValidationError,
    MockProviderForbiddenError,
    ProviderError,
    ProviderResponseError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedFormatError,
)
from app.identification.image_validation import validate_and_prepare
from app.identification.provider import IdentificationProvider, ProviderCandidate
from app.schemas.identification import (
    ConfidenceLevel,
    IdentificationCandidateOut,
    IdentificationErrorCode,
    IdentificationErrorResponse,
    IdentificationOutcome,
    IdentificationResponse,
    PhotoGuidance,
    ProviderMetaOut,
)

logger = logging.getLogger("floramw.identification.service")

# ---------------------------------------------------------------------------
# Confidence threshold helpers
# ---------------------------------------------------------------------------

_LOW_CONFIDENCE_GUIDANCE_ACTIONS = [
    "Photograph the whole plant, not just the flower.",
    "Capture clear images of the leaves, including their undersides.",
    "Include flowers or fruits if present.",
    "Use natural daylight and avoid harsh shadows.",
    "Hold the camera steady and ensure the image is in focus.",
    "Move closer to fill the frame with the plant.",
]

_NO_MATCH_GUIDANCE_ACTIONS = [
    "Take a new photograph that includes both leaves and flowers.",
    "Ensure the image is well-lit, in focus, and not blurred.",
    "Capture the whole plant from a distance, then a close-up of key features.",
    "Include any visible fruits, seeds, or seed pods.",
    "Consider consulting a local botanist for in-person identification.",
]


def _confidence_level(score: float) -> ConfidenceLevel:
    """Map a numeric confidence score to a labelled band.

    Thresholds are configuration-driven. Labels must never be presented
    as independently validated accuracy measurements.

    Precondition: score is a finite float in [0.0, 1.0]; enforced by
    _validate_candidate before this is called.
    """
    if score >= settings.CONFIDENCE_THRESHOLD_HIGH:
        return ConfidenceLevel.HIGH
    if score >= settings.CONFIDENCE_THRESHOLD_MODERATE:
        return ConfidenceLevel.MODERATE
    if score >= settings.CONFIDENCE_THRESHOLD_LOW:
        return ConfidenceLevel.LOW
    return ConfidenceLevel.UNCERTAIN


def _low_confidence_guidance(reason: str) -> PhotoGuidance:
    return PhotoGuidance(
        suggested_actions=_LOW_CONFIDENCE_GUIDANCE_ACTIONS,
        reason=reason,
    )


def _no_match_guidance() -> PhotoGuidance:
    return PhotoGuidance(
        suggested_actions=_NO_MATCH_GUIDANCE_ACTIONS,
        reason=(
            "No species candidates were found. The photograph may not contain "
            "enough distinctive botanical features for identification."
        ),
    )


# ---------------------------------------------------------------------------
# Candidate validation
# ---------------------------------------------------------------------------


def _validate_candidate(candidate: ProviderCandidate) -> ProviderCandidate | None:
    """Return the candidate if it is structurally valid, else None.

    Invalid candidates (missing name, non-finite or out-of-range confidence)
    are discarded rather than raising — a partial result is preferable to a
    complete failure caused by one malformed candidate.

    Explicitly checks math.isfinite to reject NaN and ±Infinity, which would
    otherwise satisfy the 0.0 <= x <= 1.0 range check ambiguously.
    """
    if not candidate.scientific_name or not candidate.scientific_name.strip():
        logger.warning("Provider returned candidate with empty scientific name; discarding.")
        return None

    if not math.isfinite(candidate.confidence):
        logger.warning(
            "Provider returned candidate '%s' with non-finite confidence %r; discarding.",
            candidate.scientific_name,
            candidate.confidence,
        )
        return None

    if not (0.0 <= candidate.confidence <= 1.0):
        logger.warning(
            "Provider returned candidate '%s' with out-of-range confidence %r; discarding.",
            candidate.scientific_name,
            candidate.confidence,
        )
        return None

    return candidate


# ---------------------------------------------------------------------------
# HTTPException factory helpers
# ---------------------------------------------------------------------------


def _image_error(
    error_code: IdentificationErrorCode,
    message: str,
    http_status: int,
    retryable: bool = False,
) -> HTTPException:
    """Build a structured HTTPException for image validation failures."""
    return HTTPException(
        status_code=http_status,
        detail=IdentificationErrorResponse(
            error_code=error_code,
            message=message,
            retryable=retryable,
        ).model_dump(mode="json"),
    )


def _provider_error(
    error_code: IdentificationErrorCode,
    message: str,
    http_status: int,
    retryable: bool = False,
) -> HTTPException:
    """Build a structured HTTPException for provider failures."""
    return HTTPException(
        status_code=http_status,
        detail=IdentificationErrorResponse(
            error_code=error_code,
            message=message,
            retryable=retryable,
        ).model_dump(mode="json"),
    )


# ---------------------------------------------------------------------------
# Main service function
# ---------------------------------------------------------------------------


async def run_identification(
    raw_bytes: bytes,
    declared_content_type: str | None,
    provider: IdentificationProvider,
    db: AsyncSession,
    client_request_id: str | None = None,
) -> IdentificationResponse:
    """Execute the full identification workflow.

    Returns:
        IdentificationResponse (HTTP 200) when the image is valid and the
        provider has processed the request, regardless of whether candidates
        were found.

    Raises:
        HTTPException (400): Empty or corrupted image.
        HTTPException (413): Image exceeds size limit.
        HTTPException (415): Unsupported image format.
        HTTPException (422): Image dimensions exceed limit.
        HTTPException (502): Provider returned an invalid response.
        HTTPException (503): Provider unavailable or identification disabled.
        HTTPException (504): Provider timed out.
    """
    # ------------------------------------------------------------------
    # Step 1: Image validation — raises HTTPException on failure
    # ------------------------------------------------------------------
    try:
        image_payload = validate_and_prepare(raw_bytes, declared_content_type)
    except EmptyUploadError as exc:
        raise _image_error(
            IdentificationErrorCode.IMAGE_EMPTY,
            "The uploaded file is empty. Please select a valid photograph.",
            http_status=400,
        ) from exc
    except FileTooLargeError as exc:
        raise _image_error(
            IdentificationErrorCode.IMAGE_TOO_LARGE,
            (
                f"The uploaded file is too large "
                f"({exc.actual_bytes // (1024 * 1024)} MB). "
                f"Maximum allowed size is {exc.limit_bytes // (1024 * 1024)} MB."
            ),
            http_status=413,
        ) from exc
    except UnsupportedFormatError as exc:
        raise _image_error(
            IdentificationErrorCode.IMAGE_FORMAT_UNSUPPORTED,
            "Unsupported image format. Please upload a JPEG or PNG photograph.",
            http_status=415,
        ) from exc
    except ImageDimensionError as exc:
        raise _image_error(
            IdentificationErrorCode.IMAGE_DIMENSIONS_EXCEEDED,
            (
                f"The image is too large ({exc.width}×{exc.height} px). "
                f"Maximum dimension is {exc.max_dim} px per side. "
                "Please resize the image before uploading."
            ),
            http_status=422,
        ) from exc
    except ImageDecodingError as exc:
        raise _image_error(
            IdentificationErrorCode.IMAGE_DECODING_FAILED,
            (
                "The uploaded file could not be read as an image. "
                "It may be corrupted or truncated. Please try a different photograph."
            ),
            http_status=400,
        ) from exc
    except ImageValidationError as exc:
        # Catch-all for any other ImageValidationError subclass
        raise _image_error(
            IdentificationErrorCode.IMAGE_DECODING_FAILED,
            "The uploaded image could not be validated. Please try a different photograph.",
            http_status=400,
        ) from exc

    # ------------------------------------------------------------------
    # Step 2: Provider invocation — raises HTTPException on failure
    # ------------------------------------------------------------------
    is_demo = provider.provider_id.startswith("floramw-deterministic")

    try:
        provider_result = await provider.identify(image_payload)
    except MockProviderForbiddenError as exc:
        logger.error("Mock provider forbidden in this environment: %s", exc)
        raise _provider_error(
            IdentificationErrorCode.IDENTIFICATION_DISABLED,
            (
                "Plant identification is not available in this environment. "
                "Contact the application administrator to configure a provider."
            ),
            http_status=503,
            retryable=False,
        ) from exc
    except ProviderUnavailableError as exc:
        logger.warning("Provider unavailable: %s", exc)
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_UNAVAILABLE,
            "The identification service is temporarily unavailable. Please try again shortly.",
            http_status=503,
            retryable=True,
        ) from exc
    except ProviderTimeoutError as exc:
        logger.warning("Provider timeout: %s", exc)
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_TIMEOUT,
            "The identification request timed out. Please retry with a stable connection.",
            http_status=504,
            retryable=True,
        ) from exc
    except (ProviderResponseError, ProviderError) as exc:
        logger.error("Provider error: %s", exc)
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_ERROR,
            "The identification service returned an unexpected response. This has been logged.",
            http_status=502,
            retryable=False,
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error from provider: %s", exc)
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_ERROR,
            "An unexpected error occurred during identification. This has been logged.",
            http_status=502,
            retryable=False,
        ) from exc

    # ------------------------------------------------------------------
    # Step 3: Validate and filter provider candidates
    # ------------------------------------------------------------------
    valid_candidates = [
        c for c in (
            _validate_candidate(pc) for pc in provider_result.candidates
        )
        if c is not None
    ]

    now = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # Step 4: Handle no-match case — HTTP 200, outcome NO_MATCH
    # ------------------------------------------------------------------
    if not valid_candidates:
        return IdentificationResponse(
            outcome=IdentificationOutcome.NO_MATCH,
            candidates=[],
            top_confidence_level=None,
            photo_guidance=_no_match_guidance(),
            provider=ProviderMetaOut(
                provider_id=provider_result.provider_id,
                model_version=provider_result.model_version,
                is_demo=is_demo,
            ),
            client_request_id=client_request_id,
            created_at=now,
        )

    # ------------------------------------------------------------------
    # Step 5: Catalogue matching and candidate enrichment
    # ------------------------------------------------------------------
    enriched: list[IdentificationCandidateOut] = []
    for pc in valid_candidates:
        level = _confidence_level(pc.confidence)
        matched = False
        plant_id = None
        try:
            match = await match_scientific_name(pc.scientific_name, db)
            matched = match.matched
            plant_id = match.plant_id
        except Exception as exc:
            logger.warning(
                "Catalogue match query failed for '%s': %s",
                pc.scientific_name,
                exc,
            )
            # Treat as unmatched — do not fail the whole request

        enriched.append(
            IdentificationCandidateOut(
                scientific_name=pc.scientific_name,
                common_names=pc.common_names,
                confidence=pc.confidence,
                confidence_level=level,
                family=pc.family,
                genus=pc.genus,
                catalogue_matched=matched,
                catalogue_plant_id=plant_id,
                provider_notes=pc.notes,
            )
        )

    # Sort by confidence descending (provider may already sort, but enforce it)
    enriched.sort(key=lambda c: c.confidence, reverse=True)

    # ------------------------------------------------------------------
    # Step 6: Determine top-level outcome and guidance
    # ------------------------------------------------------------------
    top_candidate = enriched[0]
    top_level = top_candidate.confidence_level

    outcome = IdentificationOutcome.DEMO_MODE if is_demo else IdentificationOutcome.CANDIDATES

    photo_guidance: PhotoGuidance | None = None
    if top_level in (ConfidenceLevel.LOW, ConfidenceLevel.UNCERTAIN):
        photo_guidance = _low_confidence_guidance(
            reason=(
                f"The highest-confidence candidate has {top_level.value} confidence "
                f"({top_candidate.confidence:.0%}). The photograph may not show "
                "enough distinctive features for a reliable identification."
            )
        )

    return IdentificationResponse(
        outcome=outcome,
        candidates=enriched,
        top_confidence_level=top_level,
        photo_guidance=photo_guidance,
        provider=ProviderMetaOut(
            provider_id=provider_result.provider_id,
            model_version=provider_result.model_version,
            is_demo=is_demo,
        ),
        client_request_id=client_request_id,
        created_at=now,
    )
