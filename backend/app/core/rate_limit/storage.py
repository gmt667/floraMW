"""Pluggable rate limiting storage backends for FloraMW API.

Provides:
- BaseRateLimitStorage: Abstract base class defining token bucket storage interface.
- InMemoryRateLimitStorage: In-memory token bucket implementation for local
  development and single-process deployments.
- RedisRateLimitStorage: Redis-backed token bucket using an atomic Lua script
  for production multi-worker deployments.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("floramw.rate_limit.storage")


class RateLimitResult:
    """Outcome of a token acquisition attempt."""

    __slots__ = ("allowed", "retry_after_seconds", "remaining", "limit", "reset_epoch")

    def __init__(
        self,
        allowed: bool,
        retry_after_seconds: int,
        remaining: int,
        limit: int,
        reset_epoch: int,
    ) -> None:
        self.allowed = allowed
        self.retry_after_seconds = retry_after_seconds
        self.remaining = remaining
        self.limit = limit
        self.reset_epoch = reset_epoch

    def __repr__(self) -> str:
        return (
            f"<RateLimitResult allowed={self.allowed} "
            f"retry_after={self.retry_after_seconds}s remaining={self.remaining}/{self.limit}>"
        )


class BaseRateLimitStorage(ABC):
    """Abstract interface for rate limiter storage implementations."""

    @abstractmethod
    async def acquire(
        self,
        key: str,
        rate_per_minute: float,
        burst_capacity: int,
        cost: int = 1,
    ) -> RateLimitResult:
        """Attempt to acquire tokens for the specified key using the token bucket algorithm."""
        pass

    @abstractmethod
    async def reset(self, key: Optional[str] = None) -> None:
        """Reset quota for a key, or all keys if key is None."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close connections or release resources."""
        pass


class InMemoryRateLimitStorage(BaseRateLimitStorage):
    """Thread-safe and async-safe in-memory token bucket storage.

    Stores bucket states as: key -> (tokens: float, last_refill_timestamp: float).
    Suitable for local development and single-process production deployments.
    """

    def __init__(self, cleanup_interval_seconds: float = 300.0) -> None:
        self._buckets: Dict[str, Tuple[float, float]] = {}
        self._lock = asyncio.Lock()
        self._cleanup_interval = cleanup_interval_seconds
        self._last_cleanup = time.monotonic()

    async def acquire(
        self,
        key: str,
        rate_per_minute: float,
        burst_capacity: int,
        cost: int = 1,
    ) -> RateLimitResult:
        now = time.monotonic()
        wall_now = int(time.time())
        refill_rate = rate_per_minute / 60.0

        async with self._lock:
            # Periodic cleanup of expired/stale buckets
            if now - self._last_cleanup > self._cleanup_interval:
                self._purge_stale_buckets(now)
                self._last_cleanup = now

            if key not in self._buckets:
                tokens = float(burst_capacity)
                last_refill = now
            else:
                prev_tokens, last_refill = self._buckets[key]
                elapsed = max(0.0, now - last_refill)
                tokens = min(float(burst_capacity), prev_tokens + (elapsed * refill_rate))
                last_refill = now

            if tokens >= cost:
                tokens -= cost
                self._buckets[key] = (tokens, last_refill)
                remaining = int(tokens)
                seconds_to_full = (
                    math.ceil((burst_capacity - tokens) / refill_rate)
                    if refill_rate > 0
                    else 0
                )
                return RateLimitResult(
                    allowed=True,
                    retry_after_seconds=0,
                    remaining=remaining,
                    limit=burst_capacity,
                    reset_epoch=wall_now + seconds_to_full,
                )
            else:
                self._buckets[key] = (tokens, last_refill)
                deficit = cost - tokens
                retry_after = (
                    math.ceil(deficit / refill_rate) if refill_rate > 0 else 60
                )
                return RateLimitResult(
                    allowed=False,
                    retry_after_seconds=max(1, int(retry_after)),
                    remaining=0,
                    limit=burst_capacity,
                    reset_epoch=wall_now + max(1, int(retry_after)),
                )

    def _purge_stale_buckets(self, now: float) -> None:
        """Remove buckets that have been inactive for over 1 hour and are fully replenished."""
        stale_threshold = 3600.0
        keys_to_delete = [
            k for k, (_, last_refill) in self._buckets.items()
            if now - last_refill > stale_threshold
        ]
        for k in keys_to_delete:
            del self._buckets[k]

    async def reset(self, key: Optional[str] = None) -> None:
        async with self._lock:
            if key is not None:
                self._buckets.pop(key, None)
            else:
                self._buckets.clear()

    async def close(self) -> None:
        async with self._lock:
            self._buckets.clear()


# Lua script for atomic token bucket operations in Redis
_REDIS_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local burst_capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil or last_refill == nil then
    tokens = burst_capacity
    last_refill = now
else
    local elapsed = math.max(0, now - last_refill)
    tokens = math.min(burst_capacity, tokens + (elapsed * refill_rate))
    last_refill = now
end

local allowed = 0
local retry_after = 0
local remaining = 0

if tokens >= cost then
    allowed = 1
    tokens = tokens - cost
    remaining = math.floor(tokens)
else
    allowed = 0
    local deficit = cost - tokens
    if refill_rate > 0 then
        retry_after = math.ceil(deficit / refill_rate)
    else
        retry_after = 60
    end
    remaining = 0
end

redis.call('HMSET', key, 'tokens', tostring(tokens), 'last_refill', tostring(last_refill))
redis.call('EXPIRE', key, ttl)

return {allowed, retry_after, remaining}
"""


class RedisRateLimitStorage(BaseRateLimitStorage):
    """Redis-backed distributed token bucket storage.

    Uses an atomic Lua script to guarantee race-condition-free token acquisition
    across multi-worker or multi-container deployments.
    Supports fail-open configuration when Redis is unreachable or experiences faults.
    """

    def __init__(
        self,
        redis_client: Optional[Any] = None,
        redis_url: str = "redis://localhost:6379/0",
        fail_open: bool = True,
        ttl_margin_seconds: int = 3600,
    ) -> None:
        self._client = redis_client
        self._redis_url = redis_url
        self.fail_open = fail_open
        self.ttl_margin_seconds = ttl_margin_seconds
        self._script_sha: Optional[str] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        async with self._lock:
            if self._client is None:
                try:
                    import redis.asyncio as aioredis
                    self._client = aioredis.from_url(
                        self._redis_url,
                        encoding="utf-8",
                        decode_responses=True,
                    )
                except ImportError as exc:
                    raise ImportError(
                        "The 'redis' package is required for RedisRateLimitStorage. "
                        "Install it or configure RATE_LIMIT_STORAGE='memory'."
                    ) from exc
            return self._client

    async def acquire(
        self,
        key: str,
        rate_per_minute: float,
        burst_capacity: int,
        cost: int = 1,
    ) -> RateLimitResult:
        refill_rate = rate_per_minute / 60.0
        now = time.time()
        wall_now = int(now)
        # TTL for bucket key in Redis: time to replenish completely + margin
        refill_time = (
            math.ceil(burst_capacity / refill_rate) if refill_rate > 0 else 60
        )
        ttl = refill_time + self.ttl_margin_seconds

        try:
            client = await self._get_client()
            # Execute Lua script
            res = await client.eval(
                _REDIS_TOKEN_BUCKET_LUA,
                1,
                key,
                str(burst_capacity),
                str(refill_rate),
                str(now),
                str(cost),
                str(ttl),
            )
            allowed = bool(int(res[0]))
            retry_after = max(0, int(res[1]))
            remaining = max(0, int(res[2]))

            if allowed:
                return RateLimitResult(
                    allowed=True,
                    retry_after_seconds=0,
                    remaining=remaining,
                    limit=burst_capacity,
                    reset_epoch=wall_now + (burst_capacity - remaining),
                )
            else:
                return RateLimitResult(
                    allowed=False,
                    retry_after_seconds=max(1, retry_after),
                    remaining=0,
                    limit=burst_capacity,
                    reset_epoch=wall_now + max(1, retry_after),
                )
        except Exception as exc:
            logger.warning("Redis rate limiter error for key '%s': %s", key, exc)
            if self.fail_open:
                logger.info("Failing open for key '%s' due to Redis error", key)
                return RateLimitResult(
                    allowed=True,
                    retry_after_seconds=0,
                    remaining=1,
                    limit=burst_capacity,
                    reset_epoch=wall_now,
                )
            else:
                return RateLimitResult(
                    allowed=False,
                    retry_after_seconds=60,
                    remaining=0,
                    limit=burst_capacity,
                    reset_epoch=wall_now + 60,
                )

    async def reset(self, key: Optional[str] = None) -> None:
        try:
            client = await self._get_client()
            if key is not None:
                await client.delete(key)
            else:
                keys = await client.keys("rl:*")
                if keys:
                    await client.delete(*keys)
        except Exception as exc:
            logger.warning("Error resetting Redis rate limiter: %s", exc)

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.debug("Error closing Redis client: %s", exc)
            finally:
                self._client = None

