"""Tests for District endpoints.

Validates the 28-district administrative structure across Northern (6),
Central (9) and Southern (13) regions, matching lib/locale_data.dart.
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_all_districts_no_filter(client: AsyncClient):
    """Without a region filter, all 28 districts are returned."""
    response = await client.get("/api/v1/districts")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 28
    assert len(data["items"]) == 28

    # Verify item schema
    first = data["items"][0]
    assert "id" in first
    assert "name" in first
    assert "region" in first
    assert first["region"] in ("Northern", "Central", "Southern")


@pytest.mark.asyncio
async def test_list_districts_northern_region(client: AsyncClient):
    """Northern region contains exactly 6 districts (Chitipa, Karonga, Likoma,
    Mzimba, Nkhata Bay, Rumphi) — from lib/locale_data.dart."""
    resp = await client.get("/api/v1/districts", params={"region": "Northern"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert len(data["items"]) == 6
    assert all(d["region"] == "Northern" for d in data["items"])

    names = {d["name"] for d in data["items"]}
    assert names == {"Chitipa", "Karonga", "Likoma", "Mzimba", "Nkhata Bay", "Rumphi"}


@pytest.mark.asyncio
async def test_list_districts_central_region(client: AsyncClient):
    """Central region contains exactly 9 districts."""
    resp = await client.get("/api/v1/districts", params={"region": "Central"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 9
    assert len(data["items"]) == 9
    assert all(d["region"] == "Central" for d in data["items"])

    names = {d["name"] for d in data["items"]}
    assert names == {
        "Dedza", "Dowa", "Kasungu", "Lilongwe", "Mchinji",
        "Nkhotakota", "Ntcheu", "Ntchisi", "Salima",
    }


@pytest.mark.asyncio
async def test_list_districts_southern_region(client: AsyncClient):
    """Southern region contains exactly 13 districts."""
    resp = await client.get("/api/v1/districts", params={"region": "Southern"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 13
    assert len(data["items"]) == 13
    assert all(d["region"] == "Southern" for d in data["items"])


@pytest.mark.asyncio
async def test_regional_counts_sum_to_28(client: AsyncClient):
    """Northern + Central + Southern must equal the full 28-district count."""
    north = (await client.get("/api/v1/districts", params={"region": "Northern"})).json()["total"]
    central = (await client.get("/api/v1/districts", params={"region": "Central"})).json()["total"]
    south = (await client.get("/api/v1/districts", params={"region": "Southern"})).json()["total"]
    assert north + central + south == 28


@pytest.mark.asyncio
async def test_get_district_by_id_success(client: AsyncClient):
    """Retrieve a single district by its integer ID."""
    list_resp = await client.get("/api/v1/districts")
    first = list_resp.json()["items"][0]
    dist_id = first["id"]

    resp = await client.get(f"/api/v1/districts/{dist_id}")
    assert resp.status_code == 200
    district = resp.json()
    assert district["id"] == dist_id
    assert district["name"] == first["name"]
    assert district["region"] == first["region"]


@pytest.mark.asyncio
async def test_get_district_by_id_not_found(client: AsyncClient):
    """Non-existent district ID returns 404."""
    resp = await client.get("/api/v1/districts/99999")
    assert resp.status_code == 404
    assert "detail" in resp.json()


@pytest.mark.asyncio
async def test_unknown_region_returns_empty(client: AsyncClient):
    """An unrecognised region value returns 200 with zero items."""
    resp = await client.get("/api/v1/districts", params={"region": "Eastern"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
