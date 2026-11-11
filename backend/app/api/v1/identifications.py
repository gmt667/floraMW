"""Identification API endpoint.

POST /api/v1/identifications

Accepts a multipart image upload and returns structured identification
candidates from the configured provider.

The endpoint is stateless — no identification records are persisted.
This is intentional for Phase 2.1: the Flutter frontend currently manages
identification history locally, and there is no product requirement for
server-side persistence at this stage.

Security:
- Raw bytes are read into memory, validated, and discarded; never written
  to the filesystem.
- Declared filename is never used for filesystem operations.
- Internal errors, paths, and stack traces are never exposed in responses.
- Uploaded images are not cached or logged (only size/format metadata).
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.identification.exceptions import (
    MockProviderForbiddenError,
    ProviderUnavailableError,
)
from app.identification.provider import (
    IdentificationProvider,
    get_identification_provider,
)
from app.identification.service import run_identification
from app.schemas.identification import (
    IdentificationErrorCode,
    IdentificationErrorResponse,
    IdentificationResponse,
)

logger = logging.getLogger("floramw.api.identifications")

router = APIRouter(prefix="/identifications", tags=["Plant Identification"])


def get_current_provider() -> IdentificationProvider:
    """Dependency that resolves the active provider based on configuration.

    Raises HTTPException(503) if mock is forbidden in production or provider is disabled.
    """
    try:
        return get_identification_provider()
    except MockProviderForbiddenError as exc:
        logger.error("Mock provider forbidden in current environment: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=IdentificationErrorResponse(
                error_code=IdentificationErrorCode.IDENTIFICATION_DISABLED,
                message=(
                    "Plant identification is not available in this environment. "
                    "Contact the application administrator."
                ),
                retryable=False,
            ).model_dump(mode="json"),
        ) from exc
    except ProviderUnavailableError as exc:
        logger.warning("Identification provider unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=IdentificationErrorResponse(
                error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                message=str(exc),
                retryable=True,
            ).model_dump(mode="json"),
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error resolving identification provider: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=IdentificationErrorResponse(
                error_code=IdentificationErrorCode.PROVIDER_UNAVAILABLE,
                message="Identification provider is temporarily unavailable.",
                retryable=True,
            ).model_dump(mode="json"),
        ) from exc


@router.post(
    "",
    response_model=IdentificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Identify a plant from a photograph",
    response_description=(
        "Identification candidates with confidence scores, catalogue match "
        "information, provider metadata, and a mandatory safety disclaimer."
    ),
    responses={
        status.HTTP_200_OK: {
            "model": IdentificationResponse,
            "description": "Successful identification or valid no-match result.",
        },
        status.HTTP_400_BAD_REQUEST: {
            "model": IdentificationErrorResponse,
            "description": "Bad Request: Empty upload, corrupt image, or invalid request ID header.",
        },
        413: {
            "model": IdentificationErrorResponse,
            "description": "Payload Too Large: Uploaded file exceeds configured size limit.",
        },
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
            "model": IdentificationErrorResponse,
            "description": "Unsupported Media Type: Format is not JPEG or PNG.",
        },
        422: {
            "model": IdentificationErrorResponse,
            "description": "Unprocessable Entity: Pixel dimensions exceed limit or missing fields.",
        },
        status.HTTP_502_BAD_GATEWAY: {
            "model": IdentificationErrorResponse,
            "description": "Bad Gateway: Identification provider returned an invalid response.",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": IdentificationErrorResponse,
            "description": "Service Unavailable: Provider offline, disabled, or mock forbidden in production.",
        },
        status.HTTP_504_GATEWAY_TIMEOUT: {
            "model": IdentificationErrorResponse,
            "description": "Gateway Timeout: Identification provider request timed out.",
        },
    },
)
async def identify_plant(
    image: UploadFile = File(
        ...,
        description=(
            "Plant photograph to identify. "
            "Accepted formats: JPEG, PNG (WebP supported where available). "
            f"Maximum size: {settings.MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB. "
            f"Maximum dimension: {settings.MAX_IMAGE_DIMENSION_PX} px."
        ),
    ),
    x_client_request_id: Optional[str] = Header(
        None,
        alias="X-Client-Request-Id",
        description="Optional client-generated UUID for request tracking and future deduplication.",
    ),
    provider: IdentificationProvider = Depends(get_current_provider),
    db: AsyncSession = Depends(get_db),
) -> IdentificationResponse:
    """Submit a plant photograph for identification.

    **Provider Configuration**: Uses the provider configured by `IDENTIFICATION_PROVIDER`.
    In development with mock enabled, returns illustrative candidates from the FloraMW
    catalogue with `provider.is_demo: true` and `outcome: demo_mode`.
    In production, mock identification is strictly forbidden and returns HTTP 503.

    **HTTP Status Semantics**:
    - `200`: Successful processing (candidates found or no-match).
    - `400`: Empty upload or corrupt/unreadable image.
    - `413`: File exceeds upload size limit.
    - `415`: Format not supported (not JPEG, PNG, or WebP).
    - `422`: Pixel dimensions exceed maximum or multipart structure invalid.
    - `502`: Provider returned a malformed response.
    - `503`: Provider is unreachable, unconfigured, or mock is forbidden in production.
    - `504`: Provider timed out.

    **Botanical Safety**: Identification results, including high-confidence matches,
    are not a substitute for expert botanical assessment. The `safety_disclaimer`
    field in every response must be displayed to the user.
    """
    client_req_id = None
    if x_client_request_id is not None:
        client_req_id = x_client_request_id.strip()
        if len(client_req_id) > 64:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=IdentificationErrorResponse(
                    error_code=IdentificationErrorCode.IMAGE_DECODING_FAILED,
                    message="X-Client-Request-Id exceeds maximum allowed length of 64 characters.",
                    retryable=False,
                ).model_dump(mode="json"),
            )

    # Read upload bytes; size enforcement happens in validate_and_prepare
    raw_bytes = await image.read()

    logger.info(
        "Identification request: filename='%s', content_type='%s', size=%d bytes, request_id='%s'",
        image.filename or "<unnamed>",
        image.content_type or "<unknown>",
        len(raw_bytes),
        client_req_id or "<none>",
    )

    response = await run_identification(
        raw_bytes=raw_bytes,
        declared_content_type=image.content_type,
        provider=provider,
        db=db,
        client_request_id=client_req_id,
    )

    return response
