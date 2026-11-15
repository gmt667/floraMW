"""ASGI Rate Limiting Middleware for FloraMW API.

Intercepts requests to identification and catalogue endpoints, enforces token
bucket rate limits and burst allowances, provides Retry-After indications,
and ensures idempotent replays retain their original database semantics.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, Sequence
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.core.rate_limit.limiter import RateLimiter, get_rate_limiter
from app.schemas.identification import (
    IdentificationErrorCode,
    IdentificationErrorResponse,
)

logger = logging.getLogger("floramw.rate_limit.middleware")


class RateLimitMiddleware:
    """Enforces rate limits on FloraMW API endpoints."""

    def __init__(
        self,
        app: ASGIApp,
        limiter: Optional[RateLimiter] = None,
        ident_path: str = f"{settings.API_V1_STR}/identifications",
        auth_path: str = f"{settings.API_V1_STR}/auth",
        catalogue_paths: Sequence[str] = (
            f"{settings.API_V1_STR}/plants",
            f"{settings.API_V1_STR}/districts",
        ),
    ) -> None:
        self.app = app
        self._limiter = limiter
        self.ident_path = ident_path
        self.auth_path = auth_path
        self.catalogue_paths = tuple(catalogue_paths)

    @property
    def limiter(self) -> RateLimiter:
        if self._limiter is not None:
            return self._limiter
        return get_rate_limiter()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "")
        method: str = scope.get("method", "")

        category: Optional[str] = None
        client_request_id: Optional[str] = None

        if method == "POST" and path.startswith(self.ident_path):
            category = "identification"
            headers_dict = dict(scope.get("headers", []))
            raw_id = headers_dict.get(b"x-client-request-id")
            if raw_id:
                try:
                    client_request_id = raw_id.decode("ascii", errors="ignore").strip()
                except Exception:
                    pass
        elif method == "GET" and any(path.startswith(p) for p in self.catalogue_paths):
            category = "catalogue"
        elif method == "POST" and path.startswith(self.auth_path):
            category = "auth"

        if category is None:
            # Endpoint is not rate limited (e.g. /health, /, /docs, /openapi.json)
            await self.app(scope, receive, send)
            return

        result = await self.limiter.check(
            scope=scope,
            category=category,
            client_request_id=client_request_id,
        )

        if not result.allowed:
            await self._send_429_response(send, category, result)
            return

        # Request allowed: attach rate limit informational headers to response
        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-RateLimit-Limit"] = str(result.limit)
                headers["X-RateLimit-Remaining"] = str(result.remaining)
                headers["X-RateLimit-Reset"] = str(result.reset_epoch)
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _send_429_response(self, send: Send, category: str, result: Any) -> None:
        """Construct and emit a standardized FloraMW HTTP 429 response."""
        retry_after = str(result.retry_after_seconds)

        if category == "identification":
            detail = IdentificationErrorResponse(
                error_code=IdentificationErrorCode.RATE_LIMIT_EXCEEDED,
                message=(
                    f"Too many identification requests. "
                    f"Please wait {result.retry_after_seconds} seconds before retrying."
                ),
                retryable=True,
            ).model_dump(mode="json")
        elif category == "auth":
            detail = {
                "error_code": "rate_limit_exceeded",
                "message": (
                    f"Too many authentication attempts. "
                    f"Please wait {result.retry_after_seconds} seconds before retrying."
                ),
                "retryable": True,
                "details": {
                    "retry_after_seconds": result.retry_after_seconds,
                },
            }
        else:
            detail = {
                "error_code": "rate_limit_exceeded",
                "message": (
                    f"Too many catalogue requests. "
                    f"Please wait {result.retry_after_seconds} seconds before retrying."
                ),
                "retryable": True,
                "details": {
                    "retry_after_seconds": result.retry_after_seconds,
                },
            }

        body = json.dumps({"detail": detail}).encode("utf-8")

        response_headers = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode("ascii")),
            (b"retry-after", retry_after.encode("ascii")),
            (b"x-ratelimit-limit", str(result.limit).encode("ascii")),
            (b"x-ratelimit-remaining", b"0"),
            (b"x-ratelimit-reset", str(result.reset_epoch).encode("ascii")),
        ]

        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": response_headers,
        })
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })

