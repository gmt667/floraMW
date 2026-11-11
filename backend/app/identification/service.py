"""Botanical identification application service.

Coordinates the full identification workflow:
1. Image validation and preparation (image_validation layer)
2. SHA-256 fingerprint calculation for idempotency and payload verification
3. Database reservation committed BEFORE provider invocation (two-phase lifecycle)
4. Idempotency enforcement:
   - Identical image + completed request → returns cached result (no re-inference)
   - Identical image + active processing → returns retryable HTTP 503 (no duplicate inference)
   - Identical image + expired processing → safely recovers and retries inference
   - Different image + same client_request_id → returns HTTP 409 Conflict
   - Concurrent race → resolved atomically via DB unique constraint + rollback
5. Provider invocation (IdentificationProvider)
6. Failure persistence: expected provider errors are persisted as status='failed' before raising
7. Candidate confidence validation and finite-value enforcement
8. Catalogue cross-referencing
9. Transactional completion: status='completed', candidates persisted, committed atomically
10. Structured response construction

Error handling policy:
  EmptyUploadError         → HTTP 400
  ImageDecodingError       → HTTP 400
  FileTooLargeError        → HTTP 413
  UnsupportedFormatError   → HTTP 415
  ImageDimensionError      → HTTP 422
  IdempotencyConflictError → HTTP 409
  MockProviderForbiddenError → HTTP 503 (mock forbidden in environment)
  ProviderUnavailableError → HTTP 503 (temporary; retryable)
  ProviderTimeoutError     → HTTP 504 (temporary; retryable)
  ProviderResponseError    → HTTP 502
  Unexpected Exception     → HTTP 502
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status as http_status_codes
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

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
    ProviderNetworkError,
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
    """Map a numeric confidence score to a labelled band."""
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
    """Return the candidate if it is structurally valid, else None."""
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
# HTTPException and error sanitization helpers
# ---------------------------------------------------------------------------


def _sanitize_error_message(msg: str) -> str:
    """Sanitize error message to ensure no credentials or secrets are leaked."""
    if not msg:
        return "Internal identification error."
    # Mask api-key query parameters or key strings
    sanitized = re.sub(r"(?i)(api[_-]?key|key|token|password)=([^&\s]+)", r"\1=[REDACTED]", msg)
    # Mask bearer tokens
    sanitized = re.sub(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]+", "Bearer [REDACTED]", sanitized)
    # Truncate to safe length
    return sanitized[:500]


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


def _sha256_hex(data: bytes) -> str:
    """Return lowercase hex SHA-256 digest of the given bytes."""
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Idempotency response reconstruction from database record
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
# Two-Phase Persistence Helpers: Reservation, Failure, and Completion
# ---------------------------------------------------------------------------


async def _record_failure(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    expected_lease_version: int,
    error_code: str,
    error_message: str,
    execution_duration_ms: int,
) -> bool:
    """Persist a failed identification attempt conditioned on lease fencing ownership.

    Returns True if successfully persisted, or False if this worker's lease was
    superseded by a newer lease version (preventing stale failure overwrites).
    """
    try:
        stmt = (
            update(IdentificationRequest)
            .where(
                IdentificationRequest.id == request_id,
                IdentificationRequest.lease_version == expected_lease_version,
                IdentificationRequest.status == "processing",
            )
            .values(
                status="failed",
                outcome="failed",
                error_code=error_code,
                error_message=_sanitize_error_message(error_message),
                execution_duration_ms=execution_duration_ms,
                completed_at=datetime.now(timezone.utc),
            )
        )
        result = await db.execute(stmt)
        if result.rowcount == 0:
            logger.warning(
                "Stale worker failure rejected by lease fence: request_id=%s, version=%d",
                request_id,
                expected_lease_version,
            )
            await db.rollback()
            return False

        await db.commit()
        return True
    except Exception as exc:
        logger.error("Failed to persist identification failure status: %s", exc)
        await db.rollback()
        return False


async def _record_success(
    db: AsyncSession,
    request_id: uuid.UUID,
    *,
    expected_lease_version: int,
    provider_id: str,
    model_version: Optional[str],
    outcome: IdentificationOutcome,
    top_confidence_level: Optional[ConfidenceLevel],
    execution_duration_ms: int,
    enriched_candidates: list[IdentificationCandidateOut],
    now: datetime,
) -> bool:
    """Transition a reserved request to completed and persist candidates if lease is valid.

    Returns True if successfully committed, or False if this worker was fenced out
    by a newer lease recovery (preventing stale result overwrites and duplicate candidates).
    """
    model_id = None
    if provider_id == "internal":
        model_id = settings.INTERNAL_MODEL_ID

    # Step 1: Conditionally update request state only if lease_version matches exactly
    stmt = (
        update(IdentificationRequest)
        .where(
            IdentificationRequest.id == request_id,
            IdentificationRequest.lease_version == expected_lease_version,
            IdentificationRequest.status == "processing",
        )
        .values(
            status="completed",
            outcome=outcome.value,
            provider_id=provider_id,
            model_id=model_id,
            model_version=model_version,
            top_confidence_level=(
                top_confidence_level.value if top_confidence_level else None
            ),
            execution_duration_ms=execution_duration_ms,
            completed_at=now,
        )
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:
        logger.warning(
            "Stale worker completion rejected by lease fence: request_id=%s, version=%d",
            request_id,
            expected_lease_version,
        )
        await db.rollback()
        return False

    # Step 2: Insert candidates only after confirming this worker owns the active lease
    for rank, cand in enumerate(enriched_candidates, start=1):
        common_names_json = json.dumps(cand.common_names or [])
        candidate = IdentificationCandidate(
            id=uuid.uuid4(),
            request_id=request_id,
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
    return True


# ---------------------------------------------------------------------------
# Main Identification Workflow with Two-Phase Reservation
# ---------------------------------------------------------------------------


async def run_identification(
    raw_bytes: bytes,
    declared_content_type: str | None,
    provider: IdentificationProvider,
    db: AsyncSession,
    client_request_id: str | None = None,
    user_id: Optional[str] = None,
) -> IdentificationResponse:
    """Execute identification with genuine two-phase database reservation.

    Workflow:
    1. Image validation and normalization.
    2. SHA-256 fingerprint computation.
    3. Idempotency verification and processing reservation committed BEFORE provider invocation.
    4. Provider inference execution.
    5. Failure persistence on provider errors.
    6. Candidate enrichment and catalogue cross-referencing.
    7. Atomic database completion commit.
    """
    start_time = time.perf_counter()

    # ------------------------------------------------------------------
    # Step 1: Image validation
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
    # Step 2: Compute SHA-256 fingerprint and resolve client_request_id
    # ------------------------------------------------------------------
    image_sha256 = _sha256_hex(image_payload.content)
    effective_request_id = (client_request_id or "").strip() or str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    lease_seconds = getattr(settings, "IDENTIFICATION_PROCESSING_LEASE_SECONDS", 60)

    # ------------------------------------------------------------------
    # Step 3: Database Reservation BEFORE Provider Invocation
    # ------------------------------------------------------------------
    stmt = (
        select(IdentificationRequest)
        .where(IdentificationRequest.client_request_id == effective_request_id)
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()

    active_request_id: uuid.UUID
    assigned_lease_version: int

    if existing is not None:
        # Check payload fingerprint match
        if existing.image_sha256 != image_sha256:
            raise HTTPException(
                status_code=http_status_codes.HTTP_409_CONFLICT,
                detail=IdentificationErrorResponse(
                    error_code=IdentificationErrorCode.PROVIDER_ERROR,
                    message=(
                        "The provided X-Client-Request-Id was previously used with "
                        "a different image. Use a new unique identifier for each request."
                    ),
                    retryable=False,
                ).model_dump(mode="json"),
            )

        # Handle completed request -> return cached response immediately
        if existing.status == "completed":
            logger.info(
                "Returning cached identification result for client_request_id=%s",
                effective_request_id,
            )
            stmt2 = (
                select(IdentificationRequest)
                .options(selectinload(IdentificationRequest.candidates))
                .where(IdentificationRequest.id == existing.id)
            )
            result2 = await db.execute(stmt2)
            existing_with_candidates = result2.scalar_one()
            return _reconstruct_response_from_record(existing_with_candidates, client_request_id)

        # Handle active or expired processing reservation
        if existing.status == "processing":
            lease_assigned_at = getattr(existing, "lease_assigned_at", None) or existing.created_at
            if lease_assigned_at is not None and lease_assigned_at.tzinfo is None:
                lease_assigned_at = lease_assigned_at.replace(tzinfo=timezone.utc)
            elapsed = (now - lease_assigned_at).total_seconds() if lease_assigned_at else lease_seconds + 1
            if elapsed < lease_seconds:
                # Active processing by another worker: fail-closed, retryable
                logger.info(
                    "Duplicate request encountered active processing lease (elapsed: %.1fs): %s",
                    elapsed,
                    effective_request_id,
                )
                raise HTTPException(
                    status_code=http_status_codes.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=IdentificationErrorResponse(
                        error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                        message=(
                            "This identification request is currently being processed. "
                            "Please retry in a few seconds."
                        ),
                        retryable=True,
                    ).model_dump(mode="json"),
                )
            else:
                # Lease expired / abandoned processing: recover reservation with fenced increment
                logger.warning(
                    "Recovering abandoned identification lease (elapsed: %.1fs, current version: %d): %s",
                    elapsed,
                    existing.lease_version,
                    effective_request_id,
                )
                target_version = existing.lease_version
                next_version = target_version + 1
                reclaim_stmt = (
                    update(IdentificationRequest)
                    .where(
                        IdentificationRequest.id == existing.id,
                        IdentificationRequest.lease_version == target_version,
                        IdentificationRequest.status == "processing",
                    )
                    .values(
                        lease_version=next_version,
                        lease_assigned_at=now,
                        provider_id=provider.provider_id,
                    )
                )
                reclaim_res = await db.execute(reclaim_stmt)
                await db.commit()
                if reclaim_res.rowcount == 0:
                    # Race: another worker won lease reclamation or completed
                    stmt_latest = (
                        select(IdentificationRequest)
                        .options(selectinload(IdentificationRequest.candidates))
                        .where(IdentificationRequest.id == existing.id)
                    )
                    latest_res = await db.execute(stmt_latest)
                    latest_req = latest_res.scalar_one()
                    if latest_req.status == "completed":
                        return _reconstruct_response_from_record(latest_req, client_request_id)
                    raise HTTPException(
                        status_code=http_status_codes.HTTP_503_SERVICE_UNAVAILABLE,
                        detail=IdentificationErrorResponse(
                            error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                            message="This identification request is currently being processed. Please retry in a few seconds.",
                            retryable=True,
                        ).model_dump(mode="json"),
                    )

                active_request_id = existing.id
                assigned_lease_version = next_version
        else:
            # Previous attempt had failed: allow recovery/retry with fenced increment
            logger.info(
                "Retrying previously failed identification request: %s",
                effective_request_id,
            )
            target_version = existing.lease_version
            next_version = target_version + 1
            retry_stmt = (
                update(IdentificationRequest)
                .where(
                    IdentificationRequest.id == existing.id,
                    IdentificationRequest.lease_version == target_version,
                    IdentificationRequest.status == "failed",
                )
                .values(
                    lease_version=next_version,
                    lease_assigned_at=now,
                    status="processing",
                    outcome="processing",
                    error_code=None,
                    error_message=None,
                    completed_at=None,
                )
            )
            retry_res = await db.execute(retry_stmt)
            await db.commit()
            if retry_res.rowcount == 0:
                stmt_latest = (
                    select(IdentificationRequest)
                    .options(selectinload(IdentificationRequest.candidates))
                    .where(IdentificationRequest.id == existing.id)
                )
                latest_res = await db.execute(stmt_latest)
                latest_req = latest_res.scalar_one()
                if latest_req.status == "completed":
                    return _reconstruct_response_from_record(latest_req, client_request_id)
                raise HTTPException(
                    status_code=http_status_codes.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=IdentificationErrorResponse(
                        error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                        message="This identification request is currently being processed. Please retry in a few seconds.",
                        retryable=True,
                    ).model_dump(mode="json"),
                )

            active_request_id = existing.id
            assigned_lease_version = next_version

    else:
        # Create new processing reservation and commit BEFORE calling provider
        new_reservation = IdentificationRequest(
            id=uuid.uuid4(),
            client_request_id=effective_request_id,
            user_id=user_id,
            status="processing",
            outcome="processing",
            lease_version=1,
            lease_assigned_at=now,
            created_at=now,
            image_sha256=image_sha256,
            image_format=image_payload.format,
            image_size_bytes=image_payload.size_bytes,
            image_width_px=image_payload.width_px,
            image_height_px=image_payload.height_px,
            provider_id=provider.provider_id,
            model_id=None,
            model_version=None,
        )
        db.add(new_reservation)
        try:
            await db.commit()
            active_request_id = new_reservation.id
            assigned_lease_version = 1
        except IntegrityError:
            # Race condition: concurrent request inserted same client_request_id
            await db.rollback()
            stmt_race = select(IdentificationRequest).where(
                IdentificationRequest.client_request_id == effective_request_id
            )
            result_race = await db.execute(stmt_race)
            race_req = result_race.scalar_one()

            if race_req.image_sha256 != image_sha256:
                raise HTTPException(
                    status_code=http_status_codes.HTTP_409_CONFLICT,
                    detail=IdentificationErrorResponse(
                        error_code=IdentificationErrorCode.PROVIDER_ERROR,
                        message=(
                            "The provided X-Client-Request-Id was previously used with "
                            "a different image. Use a new unique identifier for each request."
                        ),
                        retryable=False,
                    ).model_dump(mode="json"),
                )

            if race_req.status == "processing":
                raise HTTPException(
                    status_code=http_status_codes.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=IdentificationErrorResponse(
                        error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                        message="This identification request is currently being processed. Please retry shortly.",
                        retryable=True,
                    ).model_dump(mode="json"),
                )

            # Concurrent request completed during race: return cached result
            stmt_cached = (
                select(IdentificationRequest)
                .options(selectinload(IdentificationRequest.candidates))
                .where(IdentificationRequest.id == race_req.id)
            )
            cached_res = await db.execute(stmt_cached)
            return _reconstruct_response_from_record(cached_res.scalar_one(), client_request_id)

    # ------------------------------------------------------------------
    # Step 4: Provider Invocation with Failure Persistence
    # ------------------------------------------------------------------
    is_demo = provider.provider_id.startswith("floramw-deterministic")

    try:
        provider_result = await provider.identify(image_payload)
    except MockProviderForbiddenError as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("Mock provider forbidden in this environment: %s", exc)
        await _record_failure(
            db,
            active_request_id,
            expected_lease_version=assigned_lease_version,
            error_code=IdentificationErrorCode.IDENTIFICATION_DISABLED.value,
            error_message=str(exc),
            execution_duration_ms=duration_ms,
        )
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
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.warning("Provider unavailable: %s", exc)
        await _record_failure(
            db,
            active_request_id,
            expected_lease_version=assigned_lease_version,
            error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE.value,
            error_message=str(exc),
            execution_duration_ms=duration_ms,
        )
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_UNAVAILABLE,
            "The identification service is temporarily unavailable. Please try again shortly.",
            http_status=503,
            retryable=True,
        ) from exc
    except ProviderTimeoutError as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.warning("Provider timeout: %s", exc)
        await _record_failure(
            db,
            active_request_id,
            expected_lease_version=assigned_lease_version,
            error_code=IdentificationErrorCode.PROVIDER_TIMEOUT.value,
            error_message=str(exc),
            execution_duration_ms=duration_ms,
        )
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_TIMEOUT,
            "The identification request timed out. Please retry with a stable connection.",
            http_status=504,
            retryable=True,
        ) from exc
    except (ProviderResponseError, ProviderNetworkError, ProviderError) as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error("Provider error: %s", exc)
        await _record_failure(
            db,
            active_request_id,
            expected_lease_version=assigned_lease_version,
            error_code=IdentificationErrorCode.PROVIDER_ERROR.value,
            error_message=str(exc),
            execution_duration_ms=duration_ms,
        )
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_ERROR,
            "The identification service returned an unexpected response. This has been logged.",
            http_status=502,
            retryable=False,
        ) from exc
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.exception("Unexpected error from provider: %s", exc)
        await _record_failure(
            db,
            active_request_id,
            expected_lease_version=assigned_lease_version,
            error_code=IdentificationErrorCode.PROVIDER_ERROR.value,
            error_message=str(exc),
            execution_duration_ms=duration_ms,
        )
        raise _provider_error(
            IdentificationErrorCode.PROVIDER_ERROR,
            "An unexpected error occurred during identification. This has been logged.",
            http_status=502,
            retryable=False,
        ) from exc

    # ------------------------------------------------------------------
    # Step 5: Candidate Validation
    # ------------------------------------------------------------------
    valid_candidates = [
        c for c in (
            _validate_candidate(pc) for pc in provider_result.candidates
        )
        if c is not None
    ]

    completed_now = datetime.now(timezone.utc)
    execution_duration_ms = int((time.perf_counter() - start_time) * 1000)

    # ------------------------------------------------------------------
    # Step 6: Handle NO_MATCH outcome
    # ------------------------------------------------------------------
    if not valid_candidates:
        committed = await _record_success(
            db,
            active_request_id,
            expected_lease_version=assigned_lease_version,
            provider_id=provider_result.provider_id,
            model_version=provider_result.model_version,
            outcome=IdentificationOutcome.NO_MATCH,
            top_confidence_level=None,
            execution_duration_ms=execution_duration_ms,
            enriched_candidates=[],
            now=completed_now,
        )
        if not committed:
            stmt_latest = (
                select(IdentificationRequest)
                .options(selectinload(IdentificationRequest.candidates))
                .where(IdentificationRequest.id == active_request_id)
            )
            latest_res = await db.execute(stmt_latest)
            latest_req = latest_res.scalar_one()
            if latest_req.status == "completed":
                return _reconstruct_response_from_record(latest_req, client_request_id)
            raise HTTPException(
                status_code=http_status_codes.HTTP_503_SERVICE_UNAVAILABLE,
                detail=IdentificationErrorResponse(
                    error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                    message="This identification request was reclaimed by another worker. Please retry shortly.",
                    retryable=True,
                ).model_dump(mode="json"),
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
    # Step 7: Catalogue matching and candidate enrichment
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

    enriched.sort(key=lambda c: c.confidence, reverse=True)

    # ------------------------------------------------------------------
    # Step 8: Determine top-level outcome and photo guidance
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
    # Step 9: Atomic Database Completion Commit
    # ------------------------------------------------------------------
    committed = await _record_success(
        db,
        active_request_id,
        expected_lease_version=assigned_lease_version,
        provider_id=provider_result.provider_id,
        model_version=provider_result.model_version,
        outcome=outcome,
        top_confidence_level=top_level,
        execution_duration_ms=execution_duration_ms,
        enriched_candidates=enriched,
        now=completed_now,
    )
    if not committed:
        stmt_latest = (
            select(IdentificationRequest)
            .options(selectinload(IdentificationRequest.candidates))
            .where(IdentificationRequest.id == active_request_id)
        )
        latest_res = await db.execute(stmt_latest)
        latest_req = latest_res.scalar_one()
        if latest_req.status == "completed":
            return _reconstruct_response_from_record(latest_req, client_request_id)
        raise HTTPException(
            status_code=http_status_codes.HTTP_503_SERVICE_UNAVAILABLE,
            detail=IdentificationErrorResponse(
                error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                message="This identification request was reclaimed by another worker. Please retry shortly.",
                retryable=True,
            ).model_dump(mode="json"),
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
