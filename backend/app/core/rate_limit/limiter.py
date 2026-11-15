"""Rate limiting engine and client identity resolution for FloraMW API.

Coordinates token bucket acquisition, client identity resolution, Malawi CGNAT
shared-IP fairness, emergency global limits, and idempotency protection.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Dict, List, Optional, Sequence
from starlette.types import Scope

from app.core.config import settings
from app.core.rate_limit.storage import (
    BaseRateLimitStorage,
    InMemoryRateLimitStorage,
    RateLimitResult,
    RedisRateLimitStorage,
)

logger = logging.getLogger("floramw.rate_limit.limiter")

_DEVICE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


class ClientIdentity:
    """Resolved client identity for rate-limiting purposes."""

    __slots__ = ("client_ip", "device_id", "is_trusted_proxy")

    def __init__(
        self,
        client_ip: str,
        device_id: Optional[str] = None,
        is_trusted_proxy: bool = False,
    ) -> None:
        self.client_ip = client_ip
        self.device_id = device_id
        self.is_trusted_proxy = is_trusted_proxy

    def __repr__(self) -> str:
        return (
            f"<ClientIdentity ip={self.client_ip} "
            f"device_id={self.device_id} trusted={self.is_trusted_proxy}>"
        )


def _sanitize_ip(raw_ip: str) -> Optional[str]:
    """Validate and normalize an IPv4 or IPv6 address."""
    clean = raw_ip.strip()
    try:
        addr = ipaddress.ip_address(clean)
        return str(addr)
    except ValueError:
        return None


def resolve_client_identity(
    scope: Scope,
    trust_proxy_headers: bool = False,
    trusted_proxies: Sequence[str] = ("127.0.0.1", "::1"),
) -> ClientIdentity:
    """Extract client IP and optional device identifier from ASGI scope.

    Security rules:
    - Direct peer IP is the default.
    - X-Forwarded-For is only parsed when direct peer IP is in `trusted_proxies`
      AND `trust_proxy_headers` is explicitly True.
    - Arbitrary client-provided forwarded headers are discarded.
    - Optional X-Device-Id header is sanitized (alphanumeric, -, _, max 64 chars).
      Device ID is strictly for burst separation on shared CGNAT and is never proof of identity.
    """
    client = scope.get("client")
    direct_ip = client[0] if client else "127.0.0.1"

    is_trusted = trust_proxy_headers and (direct_ip in trusted_proxies)
    client_ip = direct_ip

    headers_list = scope.get("headers", [])
    headers: Dict[bytes, bytes] = dict(headers_list)

    if is_trusted:
        forwarded_for = headers.get(b"x-forwarded-for")
        if forwarded_for:
            try:
                decoded = forwarded_for.decode("ascii", errors="ignore")
                # X-Forwarded-For is comma-separated: client, proxy1, proxy2...
                # Pick the leftmost valid IP
                parts = [p.strip() for p in decoded.split(",") if p.strip()]
                for part in parts:
                    validated = _sanitize_ip(part)
                    if validated:
                        client_ip = validated
                        break
            except Exception as exc:
                logger.debug("Error parsing X-Forwarded-For: %s", exc)

    # Optional Device Identifier
    device_id: Optional[str] = None
    raw_device_id = headers.get(b"x-device-id")
    if raw_device_id:
        try:
            decoded_dev = raw_device_id.decode("ascii", errors="ignore").strip()
            if _DEVICE_ID_REGEX.match(decoded_dev):
                device_id = decoded_dev
        except Exception:
            pass

    return ClientIdentity(
        client_ip=client_ip,
        device_id=device_id,
        is_trusted_proxy=is_trusted,
    )


async def is_idempotent_replay(client_request_id: Optional[str]) -> bool:
    """Check whether a client_request_id corresponds to an existing completed or processing request.

    Ensures that retried requests retaining a previously issued idempotency key
    retain their original response semantics without consuming rate-limit tokens.
    """
    if not client_request_id:
        return False

    clean_id = client_request_id.strip()
    if not clean_id or len(clean_id) > 64:
        return False

    try:
        from sqlalchemy import select
        from app.core.database import AsyncSessionLocal
        from app.models.identification import IdentificationRequest

        async with AsyncSessionLocal() as session:
            stmt = select(IdentificationRequest.status).where(
                IdentificationRequest.client_request_id == clean_id
            )
            result = await session.execute(stmt)
            status_val = result.scalar_one_or_none()
            return status_val in ("completed", "processing")
    except Exception as exc:
        logger.debug("Error checking idempotency for rate limiting: %s", exc)
        return False


class RateLimiter:
    """Core rate limiting coordinator supporting token buckets, CGNAT fairness, and idempotency."""

    def __init__(
        self,
        storage: Optional[BaseRateLimitStorage] = None,
        enabled: Optional[bool] = None,
        ident_per_minute: Optional[float] = None,
        ident_burst: Optional[int] = None,
        catalogue_per_minute: Optional[float] = None,
        catalogue_burst: Optional[int] = None,
        auth_per_minute: Optional[float] = None,
        auth_burst: Optional[int] = None,
        trust_proxy_headers: Optional[bool] = None,
        trusted_proxies: Optional[List[str]] = None,
        shared_ip_multiplier: Optional[int] = None,
        global_enabled: Optional[bool] = None,
        global_per_minute: Optional[float] = None,
        global_burst: Optional[int] = None,
    ) -> None:
        self.storage = storage or InMemoryRateLimitStorage()
        self.enabled = (
            enabled if enabled is not None else getattr(settings, "RATE_LIMIT_ENABLED", True)
        )
        self.ident_per_minute = float(
            ident_per_minute
            if ident_per_minute is not None
            else getattr(settings, "RATE_LIMIT_IDENTIFICATION_PER_MINUTE", 5)
        )
        self.ident_burst = int(
            ident_burst
            if ident_burst is not None
            else getattr(settings, "RATE_LIMIT_IDENTIFICATION_BURST", 15)
        )
        self.catalogue_per_minute = float(
            catalogue_per_minute
            if catalogue_per_minute is not None
            else getattr(settings, "RATE_LIMIT_CATALOGUE_PER_MINUTE", 60)
        )
        self.catalogue_burst = int(
            catalogue_burst
            if catalogue_burst is not None
            else getattr(settings, "RATE_LIMIT_CATALOGUE_BURST", 120)
        )
        self.auth_per_minute = float(
            auth_per_minute
            if auth_per_minute is not None
            else getattr(settings, "RATE_LIMIT_AUTH_PER_MINUTE", 10)
        )
        self.auth_burst = int(
            auth_burst
            if auth_burst is not None
            else getattr(settings, "RATE_LIMIT_AUTH_BURST", 20)
        )
        self.trust_proxy_headers = (
            trust_proxy_headers
            if trust_proxy_headers is not None
            else getattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADERS", False)
        )
        self.trusted_proxies = (
            trusted_proxies
            if trusted_proxies is not None
            else getattr(settings, "RATE_LIMIT_TRUSTED_PROXIES", ["127.0.0.1", "::1"])
        )
        self.shared_ip_multiplier = int(
            shared_ip_multiplier
            if shared_ip_multiplier is not None
            else getattr(settings, "RATE_LIMIT_SHARED_IP_BURST_MULTIPLIER", 5)
        )
        self.global_enabled = (
            global_enabled
            if global_enabled is not None
            else getattr(settings, "RATE_LIMIT_GLOBAL_ENABLED", False)
        )
        self.global_per_minute = float(
            global_per_minute
            if global_per_minute is not None
            else getattr(settings, "RATE_LIMIT_GLOBAL_PER_MINUTE", 1000)
        )
        self.global_burst = int(
            global_burst
            if global_burst is not None
            else getattr(settings, "RATE_LIMIT_GLOBAL_BURST", 2000)
        )

    async def check(
        self,
        scope: Scope,
        category: str,
        client_request_id: Optional[str] = None,
    ) -> RateLimitResult:
        """Evaluate rate limits for the given scope and endpoint category."""
        if not self.enabled:
            return RateLimitResult(
                allowed=True,
                retry_after_seconds=0,
                remaining=999,
                limit=999,
                reset_epoch=0,
            )

        # 1. Idempotency Check: Existing reservations bypass rate limiting
        if category == "identification" and client_request_id:
            if await is_idempotent_replay(client_request_id):
                logger.debug(
                    "Idempotent replay detected for request_id='%s'; bypassing rate limit",
                    client_request_id,
                )
                return RateLimitResult(
                    allowed=True,
                    retry_after_seconds=0,
                    remaining=self.ident_burst,
                    limit=self.ident_burst,
                    reset_epoch=0,
                )

        # 2. Emergency Global Brake Check
        if self.global_enabled:
            global_res = await self.storage.acquire(
                key="rl:global",
                rate_per_minute=self.global_per_minute,
                burst_capacity=self.global_burst,
                cost=1,
            )
            if not global_res.allowed:
                logger.warning("Global emergency rate limit exceeded!")
                return global_res

        # 3. Resolve Identity
        identity = resolve_client_identity(
            scope,
            trust_proxy_headers=self.trust_proxy_headers,
            trusted_proxies=self.trusted_proxies,
        )

        if category == "identification":
            rate = self.ident_per_minute
            burst = self.ident_burst
        elif category == "catalogue":
            rate = self.catalogue_per_minute
            burst = self.catalogue_burst
        elif category == "auth":
            rate = self.auth_per_minute
            burst = self.auth_burst
        else:
            rate = 60.0
            burst = 120

        # 4. Multi-Tenant Fairness (Malawi CGNAT Shared IP vs Device ID)
        if identity.device_id:
            # A. Device-specific bucket
            dev_key = f"rl:{category}:dev:{identity.device_id}"
            dev_res = await self.storage.acquire(
                key=dev_key,
                rate_per_minute=rate,
                burst_capacity=burst,
                cost=1,
            )
            if not dev_res.allowed:
                return dev_res

            # B. IP aggregate ceiling (scaled for CGNAT to prevent one IP flooding infinite device IDs)
            ip_agg_key = f"rl:{category}:ip_agg:{identity.client_ip}"
            ip_rate = rate * self.shared_ip_multiplier
            ip_burst = burst * self.shared_ip_multiplier
            ip_res = await self.storage.acquire(
                key=ip_agg_key,
                rate_per_minute=ip_rate,
                burst_capacity=ip_burst,
                cost=1,
            )
            if not ip_res.allowed:
                logger.warning(
                    "Shared IP aggregate limit reached for IP %s (device %s)",
                    identity.client_ip,
                    identity.device_id,
                )
                return ip_res

            return dev_res
        else:
            # Fallback to pure IP-based rate limiting
            ip_key = f"rl:{category}:ip:{identity.client_ip}"
            return await self.storage.acquire(
                key=ip_key,
                rate_per_minute=rate,
                burst_capacity=burst,
                cost=1,
            )

    @property
    def catalogue_rate_per_minute(self) -> float:
        return self.catalogue_per_minute
_global_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Obtain or initialize the global RateLimiter singleton."""
    global _global_limiter
    if _global_limiter is None:
        storage_type = getattr(settings, "RATE_LIMIT_STORAGE", "memory").lower()
        if storage_type == "redis":
            storage = RedisRateLimitStorage(
                redis_url=getattr(settings, "RATE_LIMIT_REDIS_URL", "redis://localhost:6379/0"),
                fail_open=getattr(settings, "RATE_LIMIT_FAIL_OPEN", True),
            )
        else:
            storage = InMemoryRateLimitStorage()
        _global_limiter = RateLimiter(storage=storage)
    return _global_limiter


def set_rate_limiter(limiter: Optional[RateLimiter]) -> None:
    """Set or reset the global RateLimiter instance (primarily for testing)."""
    global _global_limiter
    _global_limiter = limiter

