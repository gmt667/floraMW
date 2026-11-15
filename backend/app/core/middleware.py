"""Security and transport middlewares for FloraMW API.

Provides:
- SecurityHeadersMiddleware: Injects essential defensive HTTP security headers
  (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, and HTTPS-aware HSTS).
- UploadSizeLimitMiddleware: Enforces strict request body size limits on upload
  endpoints before full request buffering can saturate server memory.
"""

from __future__ import annotations

import json
import logging
from typing import Sequence

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings
from app.schemas.identification import (
    IdentificationErrorCode,
    IdentificationErrorResponse,
)

logger = logging.getLogger("floramw.middleware.security")


class PayloadTooLargeError(Exception):
    """Raised when an incoming streamed payload exceeds the configured limit."""
    pass


class SecurityHeadersMiddleware:
    """Injects defensive HTTP security headers into all responses.

    Headers applied:
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - Referrer-Policy: strict-origin-when-cross-origin
    - Strict-Transport-Security: Emitted only when the request is over HTTPS
      (or forwarded via HTTPS) and HSTS is explicitly enabled or running in production.
      Never emitted over plain HTTP in local development.
    """

    def __init__(
        self,
        app: ASGIApp,
        enable_hsts: bool = False,
        hsts_max_age: int = 31536000,
        include_subdomains: bool = True,
    ) -> None:
        self.app = app
        self.enable_hsts = enable_hsts
        self.hsts_max_age = hsts_max_age
        self.include_subdomains = include_subdomains

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

                # Check HTTPS status (direct TLS connection or reverse proxy termination)
                is_https = False
                if scope.get("scheme") == "https":
                    is_https = True
                else:
                    raw_headers = dict(scope.get("headers", []))
                    proto = raw_headers.get(b"x-forwarded-proto", b"").decode("ascii", errors="ignore").lower()
                    if proto == "https":
                        is_https = True

                # Apply HSTS only when served over HTTPS (never on plain HTTP in dev)
                effective_hsts = self.enable_hsts or getattr(settings, "ENABLE_HSTS", False)
                if is_https and (effective_hsts or settings.ENVIRONMENT == "production"):
                    hsts_val = f"max-age={self.hsts_max_age}"
                    if self.include_subdomains:
                        hsts_val += "; includeSubDomains"
                    headers["Strict-Transport-Security"] = hsts_val

            await send(message)

        await self.app(scope, receive, send_wrapper)


class UploadSizeLimitMiddleware:
    """Enforces request body size limits on file upload endpoints.

    Protects server memory and disk space against denial-of-service from oversized
    request bodies. Inspects Content-Length early when available, and enforces a
    bounded chunk reception ceiling during streaming when Content-Length is omitted
    or chunked.
    """

    def __init__(
        self,
        app: ASGIApp,
        max_upload_bytes: int = settings.MAX_UPLOAD_SIZE_BYTES,
        overhead_allowance: int = 65536,
        upload_paths: Sequence[str] = (f"{settings.API_V1_STR}/identifications",),
    ) -> None:
        self.app = app
        self.max_body_bytes = max_upload_bytes + overhead_allowance
        self.max_upload_mb = max_upload_bytes // (1024 * 1024)
        self.upload_paths = tuple(upload_paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not any(path.startswith(p) for p in self.upload_paths):
            await self.app(scope, receive, send)
            return

        # 1. Early Content-Length check before consuming body
        headers = dict(scope.get("headers", []))
        cl_header = headers.get(b"content-length")
        if cl_header:
            try:
                content_length = int(cl_header.decode("ascii"))
                if content_length > self.max_body_bytes:
                    logger.warning(
                        "Upload rejected by Content-Length check: %d bytes (limit: %d bytes)",
                        content_length,
                        self.max_body_bytes,
                    )
                    await self._send_413_response(send)
                    return
            except (ValueError, UnicodeDecodeError):
                pass

        # 2. Streaming chunk ceiling (protects against missing/falsified Content-Length)
        total_received = 0
        limit_exceeded = False
        response_sent = False

        async def bounded_receive() -> Message:
            nonlocal total_received, limit_exceeded
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                total_received += len(body)
                if total_received > self.max_body_bytes:
                    limit_exceeded = True
                    logger.warning(
                        "Upload rejected by streaming ceiling: %d bytes (limit: %d bytes)",
                        total_received,
                        self.max_body_bytes,
                    )
                    raise PayloadTooLargeError("Payload exceeds upload size limit")
            return message

        async def wrapped_send(message: Message) -> None:
            nonlocal response_sent
            if limit_exceeded:
                if message["type"] == "http.response.start" and not response_sent:
                    response_sent = True
                    await self._send_413_response(send)
                return
            await send(message)

        try:
            await self.app(scope, bounded_receive, wrapped_send)
        except Exception:
            if limit_exceeded and not response_sent:
                response_sent = True
                await self._send_413_response(send)

    async def _send_413_response(self, send: Send) -> None:
        err_payload = json.dumps({
            "detail": IdentificationErrorResponse(
                error_code=IdentificationErrorCode.IMAGE_TOO_LARGE,
                message=(
                    f"The uploaded file is too large. "
                    f"Maximum allowed size is {self.max_upload_mb} MB."
                ),
                retryable=False,
            ).model_dump(mode="json")
        }).encode("utf-8")

        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(err_payload)).encode("ascii")),
            ],
        })
        await send({
            "type": "http.response.body",
            "body": err_payload,
        })
