"""Authentication schemas for FloraMW.

Defines payloads for anonymous-device identity creation and error responses.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.identification import IdentificationErrorCode


class AnonymousAuthResponse(BaseModel):
    """Response payload returned upon issuance of an anonymous device identity.

    The raw `device_token` is returned only once at creation time and must be
    stored locally by the client for subsequent `Authorization: Bearer <token>` headers.
    """

    user_id: uuid.UUID = Field(
        description="Assigned unique identifier for the anonymous user account."
    )
    device_token: str = Field(
        description="Raw 256-bit cryptographically secure device token. Returned only once."
    )
    token_type: str = Field(
        default="bearer",
        description="HTTP Authorization scheme (Bearer).",
    )
    role: str = Field(
        default="guest",
        description="Assigned role for this anonymous device account.",
    )
    is_anonymous: bool = Field(
        default=True,
        description="True for anonymous device identities.",
    )
    created_at: datetime = Field(
        description="Timestamp when the anonymous account was issued.",
    )


class AuthErrorResponse(BaseModel):
    """Structured error payload for authentication failures (HTTP 401)."""

    error_code: IdentificationErrorCode
    message: str
    retryable: bool = False

