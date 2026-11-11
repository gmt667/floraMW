"""Tests for Root and Health endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Verify service root metadata."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "service" in data
    assert "version" in data
    assert data["docs"] == "/docs"


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Verify health status and database connectivity."""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


# ---------------------------------------------------------------------------
# F-1: CORS credentials must not be sent when allow_origins is wildcard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cors_wildcard_origin_credentials_header_absent(client: AsyncClient):
    """With wildcard CORS_ORIGINS (default dev config), Access-Control-Allow-Credentials must not be 'true'.

    The CORS specification forbids pairing allow_credentials=True with a wildcard
    allow_origins value. Browsers reject such responses outright. This test verifies
    that the backend does not emit the credentials header when the default wildcard
    origin is configured.
    """
    resp = await client.get("/api/v1/plants", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    acao_cred = resp.headers.get("access-control-allow-credentials", "")
    assert acao_cred.lower() != "true", (
        "CORS Access-Control-Allow-Credentials must not be 'true' when "
        "allow_origins=['*'] — browsers reject credentialed wildcard responses per CORS spec."
    )

