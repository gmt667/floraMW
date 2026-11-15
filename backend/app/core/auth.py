"""Authentication core utilities and FastAPI dependencies for FloraMW.

Provides cryptographic token generation, SHA-256 token hashing,
and user resolution dependencies (get_current_user, get_optional_current_user).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import AuthErrorResponse
from app.schemas.identification import IdentificationErrorCode

logger = logging.getLogger("floramw.auth")


def hash_device_token(raw_token: str) -> str:
    """Compute deterministic SHA-256 hex digest of a raw device token."""
    return hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()


def generate_device_token() -> tuple[str, str]:
    """Generate a cryptographically secure 256-bit random device token.

    Returns:
        (raw_token, token_hash) tuple. Only the raw_token is returned to the client;
        only token_hash is ever stored in the database.
    """
    raw_token = secrets.token_hex(32)  # 64 hex characters = 256 bits of entropy
    token_hash = hash_device_token(raw_token)
    return raw_token, token_hash


async def get_optional_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    """Resolve an authenticated User if an Authorization header is supplied.

    Returns None if no Authorization header is present (anonymous/unauthenticated caller).
    Raises HTTP 401 if an Authorization header is provided but invalid or unrecognized.
    """
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.strip():
        return None

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        logger.warning("Rejected malformed Authorization header scheme: '%s'", scheme)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(
                error_code=IdentificationErrorCode.AUTHENTICATION_FAILED,
                message="Malformed Authorization header. Format must be 'Bearer <token>'.",
                retryable=False,
            ).model_dump(mode="json"),
        )

    token_hash = hash_device_token(token)
    stmt = select(User).where(User.device_token_hash == token_hash)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None:
        logger.warning("Authentication failed: unrecognized device token hash")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(
                error_code=IdentificationErrorCode.AUTHENTICATION_FAILED,
                message="Invalid or expired device token.",
                retryable=False,
            ).model_dump(mode="json"),
        )

    return user


async def get_current_user(
    current_user: Optional[User] = Depends(get_optional_current_user),
) -> User:
    """FastAPI dependency requiring an authenticated User.

    Raises HTTP 401 if no valid Authorization header was provided.
    """
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=AuthErrorResponse(
                error_code=IdentificationErrorCode.AUTHENTICATION_REQUIRED,
                message="Authentication required. Provide a valid 'Authorization: Bearer <token>' header.",
                retryable=False,
            ).model_dump(mode="json"),
        )

    return current_user

