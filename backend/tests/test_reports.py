"""Tests for botanical correction and feedback report endpoints.

Covers:
1. Submitting a report with flower_id (POST /api/v1/flowers/reports and /reports)
2. Submitting a general report without flower_id
3. Validation of topic and details length
4. Listing reports
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_report_for_flower_success(client: AsyncClient):
    """Submitting a botanical correction report for a valid flower returns 201."""
    payload = {
        "flower_id": "hibiscus",
        "topic": "Local name or language wording",
        "details": "Chichewa local name in Southern region is Chidole.",
        "source": "Zomba herbalist consultation",
    }
    response = await client.post("/api/v1/flowers/reports", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["flower_id"] == "hibiscus"
    assert data["plant_id"] == "hibiscus"
    assert data["topic"] == "Local name or language wording"
    assert data["details"] == "Chichewa local name in Southern region is Chidole."
    assert data["source"] == "Zomba herbalist consultation"
    assert data["status"] == "submitted"
    assert "id" in data
    assert "createdAt" in data


@pytest.mark.asyncio
async def test_create_report_with_legacy_plant_id(client: AsyncClient):
    """Submitting with plant_id from Flutter DraftsScreen returns 201."""
    payload = {
        "plant_id": "periwinkle",
        "topic": "Medicinal claim or safety warning",
        "details": "Ensure toxic alkaloid warning is prominent.",
        "status": "local-draft",
    }
    response = await client.post("/api/v1/reports", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["flower_id"] == "periwinkle"
    assert data["plant_id"] == "periwinkle"
    assert data["topic"] == "Medicinal claim or safety warning"


@pytest.mark.asyncio
async def test_create_general_report_without_flower_id(client: AsyncClient):
    """General feedback without a flower reference succeeds."""
    payload = {
        "topic": "Other issue",
        "details": "Need support for Tumbuka language pack.",
    }
    response = await client.post("/api/v1/flowers/reports", json=payload)
    assert response.status_code == 201
    assert response.json()["flower_id"] is None


@pytest.mark.asyncio
async def test_create_report_invalid_flower_returns_404(client: AsyncClient):
    """Report with non-existent flower ID returns 404."""
    payload = {
        "flower_id": "nonexistent-species",
        "topic": "Botanical accuracy",
        "details": "Details here...",
    }
    response = await client.post("/api/v1/flowers/reports", json=payload)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_reports_success(client: AsyncClient):
    """Listing reports returns submitted items."""
    # Create one
    await client.post(
        "/api/v1/flowers/reports",
        json={"topic": "Test topic", "details": "Some test details for listing"},
    )
    response = await client.get("/api/v1/flowers/reports")
    assert response.status_code == 200
    assert response.json()["total"] >= 1
