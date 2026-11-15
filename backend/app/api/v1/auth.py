"""Authentication API router for FloraMW.

Endpoints:
- POST /api/v1/auth/anonymous — Issue a new anonymous-device identity and token.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import generate_device_token
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import AnonymousAuthResponse, AuthErrorResponse
from app.schemas.identification import IdentificationErrorCode

logger = logging.getLogger("floramw.api.auth")

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/anonymous",
    response_model=AnonymousAuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Issue anonymous device identity",
    description=(
        "Registers a new anonymous device account and returns a cryptographically "
        "secure 256-bit token. The raw token is returned ONLY in this response and "
        "must be retained by the client for future 'Authorization: Bearer <token>' headers."
    ),
    responses={
        status.HTTP_201_CREATED: {
            "model": AnonymousAuthResponse,
            "description": "Anonymous device identity created successfully.",
        },
        status.HTTP_500_INTERNAL_SERVER_ERROR: {
            "model": AuthErrorResponse,
            "description": "Failed to create device identity.",
        },
    },
)
async def create_anonymous_identity(
    db: AsyncSession = Depends(get_db),
) -> AnonymousAuthResponse:
    """Issue a new anonymous device token and persist the user record."""
    # Attempt token generation with retry on collision (astronomically unlikely for 256-bit entropy)
    max_retries = 3
    for attempt in range(max_retries):
        raw_token, token_hash = generate_device_token()
        user = User(
            is_anonymous=True,
            role="guest",
            device_token_hash=token_hash,
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
            logger.info("Issued anonymous device identity: user_id=%s", user.id)
            return AnonymousAuthResponse(
                user_id=user.id,
                device_token=raw_token,
                token_type="bearer",
                role=user.role,
                is_anonymous=user.is_anonymous,
                created_at=user.created_at,
            )
        except IntegrityError as exc:
            await db.rollback()
            logger.warning("Collision or integrity error creating anonymous user (attempt %d): %s", attempt + 1, exc)
            if attempt == max_retries - 1:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=AuthErrorResponse(
                        error_code=IdentificationErrorCode.PROVIDER_ERROR,
                        message="Unable to issue anonymous identity. Please try again.",
                        retryable=True,
                    ).model_dump(mode="json"),
                ) from exc

