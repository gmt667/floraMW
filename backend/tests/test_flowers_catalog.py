"""Tests for canonical Flower catalogue endpoints (/api/v1/flowers).

Verifies that the canonical Flower catalogue routes provide full parity with
the frontend botanical reference requirements in lib/models.dart.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_flowers_default_returns_all_four(client: AsyncClient):
    """Default flowers list returns the 4 seeded flowers matching frontend."""
    response = await client.get("/api/v1/flowers")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4
    assert data["page"] == 1
    assert data["limit"] == 20
    assert data["has_more"] is False
    assert data["total_pages"] == 1

    ids = [item["id"] for item in data["items"]]
    assert ids == ["marigold", "hibiscus", "frangipani", "periwinkle"]


@pytest.mark.asyncio
async def test_list_flowers_search_by_common_name(client: AsyncClient):
    """Search matches common name case-insensitively."""
    response = await client.get("/api/v1/flowers?q=hibiscus")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "hibiscus"
    assert data["items"][0]["name"] == "Chinese hibiscus"


@pytest.mark.asyncio
async def test_list_flowers_filter_by_category(client: AsyncClient):
    """Category filter returns only flowers matching the category."""
    response = await client.get("/api/v1/flowers?category=Garden flowers")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    ids = {item["id"] for item in data["items"]}
    assert ids == {"hibiscus", "marigold"}


@pytest.mark.asyncio
async def test_get_flower_detail_success(client: AsyncClient):
    """Fetching single flower by ID returns full sections and sources."""
    response = await client.get("/api/v1/flowers/hibiscus")
    assert response.status_code == 200
    data = response.json()

    assert data["id"] == "hibiscus"
    assert data["name"] == "Chinese hibiscus"
    assert data["scientific"] == "Hibiscus rosa-sinensis"
    assert data["family"] == "Malvaceae"
    assert data["photo_asset"] == "assets/plants/hibiscus.jpg"

    assert isinstance(data["sections"], dict)
    assert "Identifying features" in data["sections"]
    assert "Local names & knowledge" in data["sections"]

    assert isinstance(data["sources"], list)
    assert len(data["sources"]) >= 1
    assert any(s["title"] == "PMRA · mandate and regulated products" for s in data["sources"])


@pytest.mark.asyncio
async def test_get_flower_detail_not_found(client: AsyncClient):
    """Nonexistent flower slug returns 404."""
    response = await client.get("/api/v1/flowers/unknown-flower-slug")
    assert response.status_code == 404
