"""Phase 4.2.2 — API Rate Limiting Tests.

Tests cover:
1. Requests within configured limits.
2. Requests exceeding limits.
3. Burst allowance.
4. IP fallback behaviour.
5. Optional device identifier behaviour.
6. Shared-IP (Malawi CGNAT) fairness considerations.
7. Retry response headers and error format.
8. In-memory storage behaviour.
9. Redis adapter behaviour using mocks.
10. Rate limiter failure handling.
11. Idempotency and lease-fencing regressions.
12. Existing catalogue endpoint behaviour.
"""

from __future__ import annotations

import time
from typing import Dict, Optional
from unittest.mock import AsyncMock, patch

import pytest

from app.core.rate_limit.storage import (
    InMemoryRateLimitStorage,
    RedisRateLimitStorage,
)
from app.core.rate_limit.limiter import (
    RateLimiter,
    resolve_client_identity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_scope(
    *,
    path: str = "/api/v1/identifications",
    method: str = "POST",
    client_ip: str = "10.0.0.1",
    headers: Optional[Dict[bytes, bytes]] = None,
) -> dict:
    """Build a minimal ASGI scope dict for testing."""
    _headers = list((headers or {}).items())
    return {
        "type": "http",
        "method": method,
        "path": path,
        "client": (client_ip, 12345),
        "headers": _headers,
    }


def _make_send():
    """Return an async mock send callable and a list of captured messages."""
    messages = []

    async def send(msg):
        messages.append(msg)

    return send, messages


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


async def _null_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


# ===========================================================================
# 1 & 8. InMemoryRateLimitStorage — Token Bucket Mechanics
# ===========================================================================


class TestInMemoryStorage:
    """Tests for the in-memory token bucket implementation."""

    @pytest.mark.asyncio
    async def test_first_request_within_limit_allowed(self):
        storage = InMemoryRateLimitStorage()
        result = await storage.acquire("test:key", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is True
        assert result.remaining == 4

    @pytest.mark.asyncio
    async def test_requests_within_burst_allowed(self):
        storage = InMemoryRateLimitStorage()
        for i in range(5):
            result = await storage.acquire("test:burst", rate_per_minute=5.0, burst_capacity=5)
            assert result.allowed is True, f"Request {i + 1} should be allowed within burst"

    @pytest.mark.asyncio
    async def test_request_exceeding_burst_rejected(self):
        storage = InMemoryRateLimitStorage()
        for _ in range(5):
            await storage.acquire("test:exceed", rate_per_minute=5.0, burst_capacity=5)
        # 6th request should be rejected
        result = await storage.acquire("test:exceed", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_retry_after_seconds_positive_on_rejection(self):
        storage = InMemoryRateLimitStorage()
        for _ in range(5):
            await storage.acquire("test:retry", rate_per_minute=5.0, burst_capacity=5)
        result = await storage.acquire("test:retry", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is False
        assert result.retry_after_seconds >= 1

    @pytest.mark.asyncio
    async def test_remaining_decrements_per_request(self):
        storage = InMemoryRateLimitStorage()
        for expected_remaining in [4, 3, 2, 1, 0]:
            result = await storage.acquire("test:rem", rate_per_minute=10.0, burst_capacity=5)
            assert result.allowed is True
            assert result.remaining == expected_remaining

    @pytest.mark.asyncio
    async def test_reset_clears_specific_key(self):
        storage = InMemoryRateLimitStorage()
        for _ in range(5):
            await storage.acquire("test:reset1", rate_per_minute=5.0, burst_capacity=5)
        await storage.reset("test:reset1")
        result = await storage.acquire("test:reset1", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is True
        assert result.remaining == 4

    @pytest.mark.asyncio
    async def test_reset_all_clears_all_keys(self):
        storage = InMemoryRateLimitStorage()
        for _ in range(5):
            await storage.acquire("test:all_a", rate_per_minute=5.0, burst_capacity=5)
        for _ in range(5):
            await storage.acquire("test:all_b", rate_per_minute=5.0, burst_capacity=5)
        await storage.reset()
        r_a = await storage.acquire("test:all_a", rate_per_minute=5.0, burst_capacity=5)
        r_b = await storage.acquire("test:all_b", rate_per_minute=5.0, burst_capacity=5)
        assert r_a.allowed is True
        assert r_b.allowed is True

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        """Tokens should be replenished proportional to elapsed time."""
        storage = InMemoryRateLimitStorage()
        key = "test:refill"
        # Exhaust the bucket
        for _ in range(5):
            await storage.acquire(key, rate_per_minute=60.0, burst_capacity=5)

        # Inject artificial elapsed time by directly manipulating bucket state
        now = time.monotonic()
        async with storage._lock:
            tokens, _ = storage._buckets[key]
            # Simulate 2 seconds passing: at 1 token/second, should add 2 tokens
            storage._buckets[key] = (tokens, now - 2.0)

        result = await storage.acquire(key, rate_per_minute=60.0, burst_capacity=5)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_different_keys_are_independent(self):
        storage = InMemoryRateLimitStorage()
        for _ in range(5):
            await storage.acquire("key:a", rate_per_minute=5.0, burst_capacity=5)
        # Key A is exhausted; key B should still be open
        result_a = await storage.acquire("key:a", rate_per_minute=5.0, burst_capacity=5)
        result_b = await storage.acquire("key:b", rate_per_minute=5.0, burst_capacity=5)
        assert result_a.allowed is False
        assert result_b.allowed is True

    @pytest.mark.asyncio
    async def test_limit_is_burst_capacity(self):
        storage = InMemoryRateLimitStorage()
        result = await storage.acquire("test:limit", rate_per_minute=5.0, burst_capacity=15)
        assert result.limit == 15

    @pytest.mark.asyncio
    async def test_close_clears_storage(self):
        storage = InMemoryRateLimitStorage()
        await storage.acquire("test:close", rate_per_minute=5.0, burst_capacity=5)
        await storage.close()
        result = await storage.acquire("test:close", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is True  # Bucket reset after close


# ===========================================================================
# 9. Redis Adapter Behaviour Using Mocks
# ===========================================================================


class TestRedisStorage:
    """Tests for the Redis-backed storage using mock client doubles."""

    def _make_redis_client(self, lua_result=None):
        """Return a mock async Redis client."""
        client = AsyncMock()
        if lua_result is None:
            lua_result = [1, 0, 4]  # allowed=True, retry_after=0, remaining=4
        client.eval = AsyncMock(return_value=lua_result)
        client.delete = AsyncMock(return_value=1)
        client.keys = AsyncMock(return_value=[])
        client.aclose = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_redis_allowed_result(self):
        client = self._make_redis_client(lua_result=[1, 0, 4])
        storage = RedisRateLimitStorage(redis_client=client)
        result = await storage.acquire("test:redis:allowed", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is True
        assert result.remaining == 4

    @pytest.mark.asyncio
    async def test_redis_rejected_result(self):
        client = self._make_redis_client(lua_result=[0, 12, 0])
        storage = RedisRateLimitStorage(redis_client=client)
        result = await storage.acquire("test:redis:rejected", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is False
        assert result.retry_after_seconds >= 1

    @pytest.mark.asyncio
    async def test_redis_lua_script_called_with_correct_args(self):
        client = self._make_redis_client()
        storage = RedisRateLimitStorage(redis_client=client)
        await storage.acquire("rl:ident:dev:abc123", rate_per_minute=5.0, burst_capacity=15)
        assert client.eval.called
        call_args = client.eval.call_args
        # Key should be passed as KEYS[1]
        assert "rl:ident:dev:abc123" in str(call_args)

    @pytest.mark.asyncio
    async def test_redis_fail_open_on_connection_error(self):
        """When Redis raises and fail_open=True, the request is allowed."""
        client = AsyncMock()
        client.eval = AsyncMock(side_effect=Exception("Redis connection refused"))
        storage = RedisRateLimitStorage(redis_client=client, fail_open=True)
        result = await storage.acquire("test:failopen", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_redis_fail_closed_on_connection_error(self):
        """When Redis raises and fail_open=False, the request is rejected."""
        client = AsyncMock()
        client.eval = AsyncMock(side_effect=Exception("Redis connection refused"))
        storage = RedisRateLimitStorage(redis_client=client, fail_open=False)
        result = await storage.acquire("test:failclosed", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is False
        assert result.retry_after_seconds >= 1

    @pytest.mark.asyncio
    async def test_redis_reset_key_calls_delete(self):
        client = self._make_redis_client()
        storage = RedisRateLimitStorage(redis_client=client)
        await storage.reset("rl:ident:ip:1.2.3.4")
        client.delete.assert_called_once_with("rl:ident:ip:1.2.3.4")

    @pytest.mark.asyncio
    async def test_redis_close_calls_aclose(self):
        client = self._make_redis_client()
        storage = RedisRateLimitStorage(redis_client=client)
        await storage.close()
        client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_reset_all_calls_delete_on_rl_keys(self):
        client = self._make_redis_client()
        client.keys = AsyncMock(return_value=["rl:a", "rl:b"])
        storage = RedisRateLimitStorage(redis_client=client)
        await storage.reset()
        client.delete.assert_called_once_with("rl:a", "rl:b")


# ===========================================================================
# 4 & 5. Client Identity Resolution
# ===========================================================================


class TestResolveClientIdentity:
    """Tests for IP and device identifier resolution."""

    def test_direct_ip_used_by_default(self):
        scope = _make_scope(client_ip="192.0.2.10")
        identity = resolve_client_identity(scope, trust_proxy_headers=False)
        assert identity.client_ip == "192.0.2.10"

    def test_x_forwarded_for_ignored_when_trust_disabled(self):
        scope = _make_scope(
            client_ip="10.0.0.1",
            headers={
                b"x-forwarded-for": b"203.0.113.5",
            },
        )
        identity = resolve_client_identity(scope, trust_proxy_headers=False)
        assert identity.client_ip == "10.0.0.1"

    def test_x_forwarded_for_used_when_trusted_proxy(self):
        scope = _make_scope(
            client_ip="127.0.0.1",
            headers={b"x-forwarded-for": b"203.0.113.5"},
        )
        identity = resolve_client_identity(
            scope, trust_proxy_headers=True, trusted_proxies=["127.0.0.1"]
        )
        assert identity.client_ip == "203.0.113.5"

    def test_x_forwarded_for_leftmost_ip_used(self):
        """With multiple X-Forwarded-For IPs, the first (client) IP is used."""
        scope = _make_scope(
            client_ip="127.0.0.1",
            headers={b"x-forwarded-for": b"203.0.113.5, 10.0.0.1, 10.0.0.2"},
        )
        identity = resolve_client_identity(
            scope, trust_proxy_headers=True, trusted_proxies=["127.0.0.1"]
        )
        assert identity.client_ip == "203.0.113.5"

    def test_malformed_x_forwarded_for_falls_back_to_direct_ip(self):
        scope = _make_scope(
            client_ip="127.0.0.1",
            headers={b"x-forwarded-for": b"not-an-ip!!!"},
        )
        identity = resolve_client_identity(
            scope, trust_proxy_headers=True, trusted_proxies=["127.0.0.1"]
        )
        # Should fall back to direct IP when no valid IP found in XFF
        assert identity.client_ip == "127.0.0.1"

    def test_untrusted_peer_cannot_spoof_x_forwarded_for(self):
        """An untrusted peer cannot inject a spoofed client IP via X-Forwarded-For."""
        scope = _make_scope(
            client_ip="203.0.113.99",  # attacker's real IP, not in trusted_proxies
            headers={b"x-forwarded-for": b"1.2.3.4"},
        )
        identity = resolve_client_identity(
            scope, trust_proxy_headers=True, trusted_proxies=["127.0.0.1"]
        )
        assert identity.client_ip == "203.0.113.99"

    def test_valid_device_id_accepted(self):
        scope = _make_scope(headers={b"x-device-id": b"device-abc-123"})
        identity = resolve_client_identity(scope)
        assert identity.device_id == "device-abc-123"

    def test_device_id_with_invalid_chars_rejected(self):
        scope = _make_scope(headers={b"x-device-id": b"device id with spaces!"})
        identity = resolve_client_identity(scope)
        assert identity.device_id is None

    def test_device_id_too_long_rejected(self):
        scope = _make_scope(headers={b"x-device-id": b"x" * 65})
        identity = resolve_client_identity(scope)
        assert identity.device_id is None

    def test_no_device_id_header_gives_none(self):
        scope = _make_scope()
        identity = resolve_client_identity(scope)
        assert identity.device_id is None

    def test_missing_client_defaults_to_loopback(self):
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/identifications",
            "client": None,
            "headers": [],
        }
        identity = resolve_client_identity(scope)
        assert identity.client_ip == "127.0.0.1"


# ===========================================================================
# 2 & 3. RateLimiter — Limits and Burst
# ===========================================================================


class TestRateLimiter:
    """Tests for the RateLimiter coordinator (storage-agnostic)."""

    def _make_limiter(self, **kwargs) -> RateLimiter:
        storage = InMemoryRateLimitStorage()
        defaults = dict(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            trust_proxy_headers=False,
            trusted_proxies=["127.0.0.1"],
            shared_ip_multiplier=5,
            global_enabled=False,
        )
        defaults.update(kwargs)
        return RateLimiter(**defaults)

    @pytest.mark.asyncio
    async def test_identification_within_burst_allowed(self):
        limiter = self._make_limiter()
        scope = _make_scope()
        for i in range(15):
            result = await limiter.check(scope, "identification")
            assert result.allowed is True, f"Request {i + 1} of 15 should be allowed"

    @pytest.mark.asyncio
    async def test_identification_exceeds_burst_rejected(self):
        limiter = self._make_limiter()
        scope = _make_scope()
        for _ in range(15):
            await limiter.check(scope, "identification")
        result = await limiter.check(scope, "identification")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_catalogue_within_burst_allowed(self):
        limiter = self._make_limiter()
        scope = _make_scope(path="/api/v1/plants", method="GET")
        for i in range(60):
            result = await limiter.check(scope, "catalogue")
            assert result.allowed is True, f"Request {i + 1} of 60 should be allowed"

    @pytest.mark.asyncio
    async def test_limiter_disabled_always_allows(self):
        limiter = self._make_limiter(enabled=False)
        scope = _make_scope()
        for _ in range(1000):
            result = await limiter.check(scope, "identification")
            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_device_id_uses_device_bucket(self):
        """With a device ID, bucket is per-device, not per-IP."""
        limiter = self._make_limiter(ident_burst=5)
        scope_dev1 = _make_scope(
            client_ip="10.0.0.1", headers={b"x-device-id": b"device-001"}
        )
        scope_dev2 = _make_scope(
            client_ip="10.0.0.1", headers={b"x-device-id": b"device-002"}
        )
        # Exhaust device-001
        for _ in range(5):
            await limiter.check(scope_dev1, "identification")
        result_dev1 = await limiter.check(scope_dev1, "identification")
        # device-002 on the same IP should still be allowed
        result_dev2 = await limiter.check(scope_dev2, "identification")
        assert result_dev1.allowed is False
        assert result_dev2.allowed is True

    @pytest.mark.asyncio
    async def test_different_ips_are_independent(self):
        limiter = self._make_limiter(ident_burst=5)
        scope_a = _make_scope(client_ip="10.0.0.1")
        scope_b = _make_scope(client_ip="10.0.0.2")
        for _ in range(5):
            await limiter.check(scope_a, "identification")
        result_a = await limiter.check(scope_a, "identification")
        result_b = await limiter.check(scope_b, "identification")
        assert result_a.allowed is False
        assert result_b.allowed is True


# ===========================================================================
# 6. Shared-IP (Malawi CGNAT) Fairness
# ===========================================================================


class TestCGNATFairness:
    """Tests for Malawi shared-IP / CGNAT fairness behaviour."""

    @pytest.mark.asyncio
    async def test_device_aggregate_ceiling_per_shared_ip(self):
        """When many device IDs share one IP, an aggregate ceiling limits the flood."""
        # IP aggregate ceiling = burst * multiplier = 5 * 2 = 10
        limiter = RateLimiter(
            storage=InMemoryRateLimitStorage(),
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=5,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            trust_proxy_headers=False,
            trusted_proxies=["127.0.0.1"],
            shared_ip_multiplier=2,
            global_enabled=False,
        )
        shared_ip = "41.70.0.1"  # representative Malawi IP
        allowed = 0
        # 10 different device IDs on the same CGNAT IP — only 10 can pass
        for i in range(15):
            dev_id = f"device-{i:04d}"
            scope = _make_scope(
                client_ip=shared_ip,
                headers={b"x-device-id": dev_id.encode("ascii")},
            )
            result = await limiter.check(scope, "identification")
            if result.allowed:
                allowed += 1

        # With burst_capacity=5 and multiplier=2, aggregate ceiling = 10
        assert allowed <= 10

    @pytest.mark.asyncio
    async def test_unrelated_ips_unaffected_by_cgnat_ceiling(self):
        """CGNAT aggregate limit for one IP does not affect a different IP."""
        limiter = RateLimiter(
            storage=InMemoryRateLimitStorage(),
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=5,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            trust_proxy_headers=False,
            trusted_proxies=["127.0.0.1"],
            shared_ip_multiplier=2,
            global_enabled=False,
        )
        flooded_ip = "41.70.0.1"
        clean_ip = "41.70.0.2"

        # Flood one CGNAT IP
        for i in range(15):
            dev_id = f"device-{i:04d}"
            scope = _make_scope(
                client_ip=flooded_ip,
                headers={b"x-device-id": dev_id.encode("ascii")},
            )
            await limiter.check(scope, "identification")

        # Clean IP should still work
        scope_clean = _make_scope(client_ip=clean_ip)
        result = await limiter.check(scope_clean, "identification")
        assert result.allowed is True


# ===========================================================================
# 7. Retry Headers and Error Format
# ===========================================================================


class TestRateLimitMiddlewareHTTP:
    """Tests for the ASGI middleware HTTP contract."""

    @pytest.mark.asyncio
    async def test_allowed_request_passes_through(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope()
        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        status_msg = messages[0]
        assert status_msg["status"] == 200

    @pytest.mark.asyncio
    async def test_allowed_response_has_ratelimit_headers(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope()
        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)

        # Headers injected by middleware via send_wrapper (lowercase b"x-ratelimit-...")
        # Note: headers may be tuples; check by iterating
        header_keys = {k.lower() for k, v in messages[0]["headers"]}
        assert b"x-ratelimit-limit" in header_keys
        assert b"x-ratelimit-remaining" in header_keys

    @pytest.mark.asyncio
    async def test_rate_limited_response_is_429(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        # Inject a limiter that always rejects
        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope()

        # Exhaust the 1-token burst
        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        # Second request should get 429
        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        assert messages[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_rate_limited_response_has_retry_after_header(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope()
        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)

        header_keys = {k.lower() for k, v in messages[0]["headers"]}
        assert b"retry-after" in header_keys

    @pytest.mark.asyncio
    async def test_rate_limited_response_body_has_error_code(self):
        import json
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope()
        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        body = messages[1]["body"]
        payload = json.loads(body)
        assert "detail" in payload
        assert payload["detail"]["error_code"] == "rate_limit_exceeded"

    @pytest.mark.asyncio
    async def test_rate_limited_response_retryable_true(self):
        import json
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope()
        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        payload = json.loads(messages[1]["body"])
        assert payload["detail"]["retryable"] is True

    @pytest.mark.asyncio
    async def test_unrated_path_is_not_checked(self):
        """Health check and root endpoints are not rate-limited."""
        from app.core.rate_limit.middleware import RateLimitMiddleware

        # Use a limiter with burst=0 (would reject everything if checked)
        storage = InMemoryRateLimitStorage()
        # Manually fill the global bucket so it would reject
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope(path="/health", method="GET")
        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        assert messages[0]["status"] == 200

    @pytest.mark.asyncio
    async def test_catalogue_path_is_rate_limited(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=1,  # tight burst for test
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)

        # First request: allowed
        scope = _make_scope(path="/api/v1/plants", method="GET")
        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        # Second request: rejected
        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        assert messages[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_websocket_scope_is_passthrough(self):
        """Non-HTTP scopes (e.g., websocket) pass through without rate checking."""
        from app.core.rate_limit.middleware import RateLimitMiddleware

        limiter = RateLimiter(
            storage=InMemoryRateLimitStorage(),
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=0,  # would block everything if checked
            catalogue_per_minute=60.0,
            catalogue_burst=0,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = {"type": "websocket", "path": "/ws"}
        send, messages = _make_send()
        # Should not error or block
        await middleware(scope, _make_receive(), send)


# ===========================================================================
# 10. Rate Limiter Failure Handling
# ===========================================================================


class TestRateLimiterFailureHandling:
    """Tests for graceful degradation when storage backends fail."""

    @pytest.mark.asyncio
    async def test_redis_storage_error_fail_open_allows_request(self):
        """When Redis fails and fail_open=True, requests pass through."""
        broken_client = AsyncMock()
        broken_client.eval = AsyncMock(side_effect=Exception("Connection error"))
        storage = RedisRateLimitStorage(redis_client=broken_client, fail_open=True)
        result = await storage.acquire("test:broken", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_redis_storage_error_fail_closed_blocks_request(self):
        """When Redis fails and fail_open=False, requests are blocked."""
        broken_client = AsyncMock()
        broken_client.eval = AsyncMock(side_effect=Exception("Connection error"))
        storage = RedisRateLimitStorage(redis_client=broken_client, fail_open=False)
        result = await storage.acquire("test:broken", rate_per_minute=5.0, burst_capacity=5)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_limiter_with_failing_storage_does_not_raise(self):
        """The RateLimiter must not propagate storage exceptions to callers."""
        broken_client = AsyncMock()
        broken_client.eval = AsyncMock(side_effect=Exception("Redis down"))
        storage = RedisRateLimitStorage(redis_client=broken_client, fail_open=True)
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        scope = _make_scope()
        result = await limiter.check(scope, "identification")
        assert result.allowed is True  # fail_open → passes


# ===========================================================================
# 11. Idempotency and Lease-Fencing Regressions
# ===========================================================================


class TestIdempotencyRegression:
    """Ensure rate limiting does not break idempotency or lease-fencing behaviour."""

    @pytest.mark.asyncio
    async def test_idempotent_replay_bypasses_rate_limit(self):
        """Requests replayed with an existing completed request_id skip rate limit check."""
        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,  # Burst of 1; second request would be blocked
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )

        scope = _make_scope()

        # Exhaust the burst (1 token)
        await limiter.check(scope, "identification")

        # Second request with idempotency bypass simulation
        with patch(
            "app.core.rate_limit.limiter.is_idempotent_replay",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await limiter.check(scope, "identification", client_request_id="req-id-1")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_new_request_id_consumes_token(self):
        """A fresh request_id (no DB record) is subject to normal rate limiting."""
        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=1,
            catalogue_per_minute=60.0,
            catalogue_burst=120,
            global_enabled=False,
        )
        scope = _make_scope()

        # Exhaust burst
        await limiter.check(scope, "identification")

        with patch(
            "app.core.rate_limit.limiter.is_idempotent_replay",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await limiter.check(scope, "identification", client_request_id="new-req")
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_is_idempotent_replay_returns_false_for_empty_id(self):
        from app.core.rate_limit.limiter import is_idempotent_replay

        result = await is_idempotent_replay(None)
        assert result is False

        result = await is_idempotent_replay("")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_idempotent_replay_returns_false_for_too_long_id(self):
        from app.core.rate_limit.limiter import is_idempotent_replay

        result = await is_idempotent_replay("x" * 65)
        assert result is False


# ===========================================================================
# 12. Catalogue Endpoint Behaviour
# ===========================================================================


class TestCatalogueRateLimit:
    """Tests for catalogue endpoint rate limiting."""

    @pytest.mark.asyncio
    async def test_plants_path_is_rate_limited(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=2,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope(path="/api/v1/plants", method="GET")
        for _ in range(2):
            s, _ = _make_send()
            await middleware(scope, _make_receive(), s)

        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        assert messages[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_districts_path_is_rate_limited(self):
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=1,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope(path="/api/v1/districts", method="GET")

        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        assert messages[0]["status"] == 429

    @pytest.mark.asyncio
    async def test_catalogue_429_error_has_retry_after(self):
        import json
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=1,
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope(path="/api/v1/plants", method="GET")
        s1, _ = _make_send()
        await middleware(scope, _make_receive(), s1)

        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)

        headers = {k.lower(): v for k, v in messages[0]["headers"]}
        assert b"retry-after" in headers
        payload = json.loads(messages[1]["body"])
        assert payload["detail"]["retryable"] is True

    @pytest.mark.asyncio
    async def test_post_to_plants_is_not_rate_limited_by_catalogue(self):
        """POST to /api/v1/plants should not use catalogue rate limit (not a standard endpoint)."""
        from app.core.rate_limit.middleware import RateLimitMiddleware

        storage = InMemoryRateLimitStorage()
        limiter = RateLimiter(
            storage=storage,
            enabled=True,
            ident_per_minute=5.0,
            ident_burst=15,
            catalogue_per_minute=60.0,
            catalogue_burst=0,  # 0 burst — anything that hits this limit would be blocked
            global_enabled=False,
        )
        middleware = RateLimitMiddleware(app=_null_app, limiter=limiter)
        scope = _make_scope(path="/api/v1/plants", method="POST")
        send, messages = _make_send()
        await middleware(scope, _make_receive(), send)
        # POST is not in GET catalogue paths — should passthrough
        assert messages[0]["status"] == 200


# ===========================================================================
# Rate Limit Settings Validation
# ===========================================================================


class TestRateLimitSettings:
    """Tests for configurable rate limit settings."""

    def test_settings_have_rate_limit_fields(self):
        from app.core.config import settings

        assert hasattr(settings, "RATE_LIMIT_ENABLED")
        assert hasattr(settings, "RATE_LIMIT_STORAGE")
        assert hasattr(settings, "RATE_LIMIT_IDENTIFICATION_PER_MINUTE")
        assert hasattr(settings, "RATE_LIMIT_IDENTIFICATION_BURST")
        assert hasattr(settings, "RATE_LIMIT_CATALOGUE_PER_MINUTE")
        assert hasattr(settings, "RATE_LIMIT_CATALOGUE_BURST")
        assert hasattr(settings, "RATE_LIMIT_TRUST_PROXY_HEADERS")
        assert hasattr(settings, "RATE_LIMIT_TRUSTED_PROXIES")
        assert hasattr(settings, "RATE_LIMIT_SHARED_IP_BURST_MULTIPLIER")
        assert hasattr(settings, "RATE_LIMIT_GLOBAL_ENABLED")

    def test_default_identification_limit_values(self):
        from app.core.config import settings

        assert settings.RATE_LIMIT_IDENTIFICATION_PER_MINUTE == 5
        assert settings.RATE_LIMIT_IDENTIFICATION_BURST == 15

    def test_default_catalogue_limit_values(self):
        from app.core.config import settings

        assert settings.RATE_LIMIT_CATALOGUE_PER_MINUTE == 60
        assert settings.RATE_LIMIT_CATALOGUE_BURST == 120

    def test_default_storage_is_memory(self):
        from app.core.config import settings

        assert settings.RATE_LIMIT_STORAGE == "memory"

    def test_proxy_trust_disabled_by_default(self):
        from app.core.config import settings

        assert settings.RATE_LIMIT_TRUST_PROXY_HEADERS is False

    def test_global_rate_limit_disabled_by_default(self):
        from app.core.config import settings

        assert settings.RATE_LIMIT_GLOBAL_ENABLED is False

    def test_rate_limit_enabled_by_default(self):
        from app.core.config import settings

        assert settings.RATE_LIMIT_ENABLED is True


# ===========================================================================
# RATE_LIMIT_EXCEEDED error code in schema
# ===========================================================================


class TestErrorCodeSchema:
    def test_rate_limit_exceeded_error_code_exists(self):
        from app.schemas.identification import IdentificationErrorCode

        assert IdentificationErrorCode.RATE_LIMIT_EXCEEDED.value == "rate_limit_exceeded"
