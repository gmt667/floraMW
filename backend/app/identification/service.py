"""Botanical identification application service.

Coordinates the full identification workflow:
1. Image validation and preparation (image_validation layer)
2. SHA-256 fingerprint calculation for idempotency and provenance
3. Idempotency check: return cached result for duplicate client_request_id
4. Provider invocation (IdentificationProvider)
5. Candidate confidence interpretation and finite-value validation
6. Catalogue matching (catalogue_matching layer)
7. Persistence of the request and all candidates in a single transaction
8. Structured response construction

Idempotency policy:
  - client_request_id is a stable key enforced by UNIQUE constraint in the DB.
  - If a completed request with the same client_request_id exists AND the
    image SHA-256 matches, the persisted result is returned directly.
  - If the SHA-256 differs, IdempotencyConflictError (HTTP 409) is raised.
  - If a request is still 'processing' (interrupted), HTTP 503 is returned.
  - Concurrent identical submissions are safely serialised by the DB constraint.

Error handling policy (raises HTTPException with appropriate status):
  EmptyUploadError         → HTTP 400
  ImageDecodingError       → HTTP 400
  FileTooLargeError        → HTTP 413
  UnsupportedFormatError   → HTTP 415
  ImageDimensionError      → HTTP 422
  IdempotencyConflictError → HTTP 409
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

import hashlib
import json
import logging
import math
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.identification.catalogue_matching import match_scientific_name
from app.identification.exceptions import (
    EmptyUploadError,
    FileTooLargeError,
    IdempotencyConflictError,
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
from app.models.identification import IdentificationCandidate, IdentificationRequest
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
# SHA-256 image fingerprint
# ---------------------------------------------------------------------------


def _sha256_hex(data: bytes) -> str:
    """Return lowercase hex SHA-256 digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Idempotency: load persisted response from an existing request record
# ---------------------------------------------------------------------------


def _reconstruct_response_from_record(
    request: IdentificationRequest,
    client_request_id: Optional[str],
) -> IdentificationResponse:
    """Rebuild an IdentificationResponse from a persisted IdentificationRequest."""
    is_demo = request.provider_id.startswith("floramw-deterministic")

    candidates_out: list[IdentificationCandidateOut] = []
    for cand in sorted(request.candidates, key=lambda c: c.rank):
        try:
            common_names = json.loads(cand.common_names) if cand.common_names else []
        except (json.JSONDecodeError, TypeError):
            common_names = []

        level = _confidence_level(cand.confidence)
        candidates_out.append(
            IdentificationCandidateOut(
                scientific_name=cand.scientific_name,
                common_names=common_names,
                confidence=cand.confidence,
                confidence_level=level,
                family=cand.family,
                genus=cand.genus,
                catalogue_matched=cand.matched_plant_id is not None,
                catalogue_plant_id=cand.matched_plant_id,
                provider_notes=cand.notes,
            )
        )

    # Determine guidance
    outcome = IdentificationOutcome(request.outcome)
    photo_guidance = None
    if outcome == IdentificationOutcome.NO_MATCH:
        photo_guidance = _no_match_guidance()
    elif candidates_out:
        top_level = candidates_out[0].confidence_level
        if top_level in (ConfidenceLevel.LOW, ConfidenceLevel.UNCERTAIN):
            photo_guidance = _low_confidence_guidance(
                reason=(
                    f"The highest-confidence candidate has {top_level.value} confidence "
                    f"({candidates_out[0].confidence:.0%}). The photograph may not show "
                    "enough distinctive features for a reliable identification."
                )
            )

    top_confidence_level = (
        ConfidenceLevel(request.top_confidence_level)
        if request.top_confidence_level
        else None
    )

    return IdentificationResponse(
        outcome=outcome,
        candidates=candidates_out,
        top_confidence_level=top_confidence_level,
        photo_guidance=photo_guidance,
        provider=ProviderMetaOut(
            provider_id=request.provider_id,
            model_version=request.model_version,
            is_demo=is_demo,
        ),
        client_request_id=client_request_id,
        created_at=request.created_at,
    )


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


async def _persist_identification(
    db: AsyncSession,
    *,
    client_request_id: str,
    image_sha256: str,
    image_format: str,
    image_size_bytes: int,
    image_width_px: int,
    image_height_px: int,
    provider_id: str,
    model_version: Optional[str],
    outcome: IdentificationOutcome,
    top_confidence_level: Optional[ConfidenceLevel],
    execution_duration_ms: int,
    enriched_candidates: list[IdentificationCandidateOut],
    user_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> IdentificationRequest:
    """Persist the identification request and all candidate records in one transaction."""
    if now is None:
        now = datetime.now(timezone.utc)

    # Extract model_id from provider metadata if available
    model_id: Optional[str] = None
    if provider_id == "internal":
        model_id = settings.INTERNAL_MODEL_ID

    request = IdentificationRequest(
        id=uuid.uuid4(),
        client_request_id=client_request_id,
        user_id=user_id,
        status="completed",
        image_sha256=image_sha256,
        image_format=image_format,
        image_size_bytes=image_size_bytes,
        image_width_px=image_width_px,
        image_height_px=image_height_px,
        provider_id=provider_id,
        model_id=model_id,
        model_version=model_version,
        outcome=outcome.value,
        top_confidence_level=(
            top_confidence_level.value if top_confidence_level else None
        ),
        execution_duration_ms=execution_duration_ms,
        created_at=now,
        completed_at=now,
    )
    db.add(request)
    await db.flush()  # Assign PK before inserting candidates

    for rank, cand in enumerate(enriched_candidates, start=1):
        common_names_json = json.dumps(cand.common_names or [])
        candidate = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=request.id,
            rank=rank,
            scientific_name=cand.scientific_name,
            common_names=common_names_json,
            family=cand.family,
            genus=cand.genus,
            confidence=cand.confidence,
            matched_plant_id=cand.catalogue_plant_id,
            notes=cand.provider_notes,
            created_at=now,
        )
        db.add(candidate)

    await db.commit()
    await db.refresh(request)
    return request


# ---------------------------------------------------------------------------
# Main service function
# ---------------------------------------------------------------------------


async def run_identification(
    raw_bytes: bytes,
    declared_content_type: str | None,
    provider: IdentificationProvider,
    db: AsyncSession,
    client_request_id: str | None = None,
    user_id: Optional[str] = None,
) -> IdentificationResponse:
    """Execute the full identification workflow with persistence and idempotency.

    Returns:
        IdentificationResponse (HTTP 200) when the image is valid and the
        provider has processed the request, regardless of whether candidates
        were found.

    Raises:
        HTTPException (400): Empty or corrupted image.
        HTTPException (409): Idempotency conflict (same ID, different image).
        HTTPException (413): Image exceeds size limit.
        HTTPException (415): Unsupported image format.
        HTTPException (422): Image dimensions exceed limit.
        HTTPException (502): Provider returned an invalid response.
        HTTPException (503): Provider unavailable or identification disabled.
        HTTPException (504): Provider timed out.
    """
    start_time = time.perf_counter()

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
        raise _image_error(
            IdentificationErrorCode.IMAGE_DECODING_FAILED,
            "The uploaded image could not be validated. Please try a different photograph.",
            http_status=400,
        ) from exc

    # ------------------------------------------------------------------
    # Step 2: Compute SHA-256 fingerprint for idempotency and provenance
    # ------------------------------------------------------------------
    image_sha256 = _sha256_hex(image_payload.content)

    # ------------------------------------------------------------------
    # Step 3: Resolve or generate stable client_request_id
    # ------------------------------------------------------------------
    effective_request_id = (client_request_id or "").strip() or str(uuid.uuid4())

    # ------------------------------------------------------------------
    # Step 4: Idempotency check — look up existing request by client ID
    # ------------------------------------------------------------------
    stmt = (
        select(IdentificationRequest)
        .where(IdentificationRequest.client_request_id == effective_request_id)
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing is not None:
        if existing.status == "processing":
            raise HTTPException(
                status_code=503,
                detail=IdentificationErrorResponse(
                    error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                    message=(
                        "This request is still being processed. "
                        "Please retry after a brief delay."
                    ),
                    retryable=True,
                ).model_dump(mode="json"),
            )
        # Completed or failed: check SHA-256 matches
        if existing.image_sha256 != image_sha256:
            raise HTTPException(
                status_code=409,
                detail=IdentificationErrorResponse(
                    error_code=IdentificationErrorCode.PROVIDER_ERROR,
                    message=(
                        "The provided X-Client-Request-Id was previously used with "
                        "a different image. Use a new unique identifier for each request."
                    ),
                    retryable=False,
                ).model_dump(mode="json"),
            )
        # Safe duplicate: return persisted result
        logger.info(
            "Returning cached identification result for client_request_id=%s",
            effective_request_id,
        )
        # Eagerly load candidates by re-querying with joinedload
        from sqlalchemy.orm import selectinload
        stmt2 = (
            select(IdentificationRequest)
            .options(selectinload(IdentificationRequest.candidates))
            .where(IdentificationRequest.id == existing.id)
        )
        result2 = await db.execute(stmt2)
        existing_with_candidates = result2.scalar_one()
        return _reconstruct_response_from_record(existing_with_candidates, client_request_id)

    # ------------------------------------------------------------------
    # Step 5: Provider invocation — raises HTTPException on failure
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
    # Step 6: Validate and filter provider candidates
    # ------------------------------------------------------------------
    valid_candidates = [
        c for c in (
            _validate_candidate(pc) for pc in provider_result.candidates
        )
        if c is not None
    ]

    now = datetime.now(timezone.utc)
    execution_duration_ms = int((time.perf_counter() - start_time) * 1000)

    # ------------------------------------------------------------------
    # Step 7: Handle no-match case — HTTP 200, outcome NO_MATCH
    # ------------------------------------------------------------------
    if not valid_candidates:
        await _persist_identification(
            db,
            client_request_id=effective_request_id,
            image_sha256=image_sha256,
            image_format=image_payload.format,
            image_size_bytes=image_payload.size_bytes,
            image_width_px=image_payload.width_px,
            image_height_px=image_payload.height_px,
            provider_id=provider_result.provider_id,
            model_version=provider_result.model_version,
            outcome=IdentificationOutcome.NO_MATCH,
            top_confidence_level=None,
            execution_duration_ms=execution_duration_ms,
            enriched_candidates=[],
            user_id=user_id,
            now=now,
        )
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
    # Step 8: Catalogue matching and candidate enrichment
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

    # Sort by confidence descending
    enriched.sort(key=lambda c: c.confidence, reverse=True)

    # ------------------------------------------------------------------
    # Step 9: Determine top-level outcome and guidance
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

    # ------------------------------------------------------------------
    # Step 10: Persist the request and candidates
    # ------------------------------------------------------------------
    try:
        await _persist_identification(
            db,
            client_request_id=effective_request_id,
            image_sha256=image_sha256,
            image_format=image_payload.format,
            image_size_bytes=image_payload.size_bytes,
            image_width_px=image_payload.width_px,
            image_height_px=image_payload.height_px,
            provider_id=provider_result.provider_id,
            model_version=provider_result.model_version,
            outcome=outcome,
            top_confidence_level=top_level,
            execution_duration_ms=execution_duration_ms,
            enriched_candidates=enriched,
            user_id=user_id,
            now=now,
        )
    except IntegrityError:
        # Race condition: another concurrent request with the same ID just committed.
        # Roll back and treat as a successful duplicate by looking up the existing record.
        await db.rollback()
        logger.info(
            "Idempotency race resolved for client_request_id=%s", effective_request_id
        )
        from sqlalchemy.orm import selectinload
        stmt3 = (
            select(IdentificationRequest)
            .options(selectinload(IdentificationRequest.candidates))
            .where(IdentificationRequest.client_request_id == effective_request_id)
        )
        result3 = await db.execute(stmt3)
        existing3 = result3.scalar_one_or_none()
        if existing3:
            return _reconstruct_response_from_record(existing3, client_request_id)
        # Persistence failed entirely after race resolution; return the in-memory result
        logger.error(
            "Could not resolve idempotency race for client_request_id=%s", effective_request_id
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
