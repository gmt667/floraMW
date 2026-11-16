"""Tests for Field Journal observation endpoints.

Covers:
1. Recording an observation (POST /api/v1/flowers/observations and /api/v1/observations)
2. Listing observations (GET /api/v1/flowers/observations)
3. Reading single observation (GET /api/v1/flowers/observations/{id})
4. Updating notes/district (PATCH /api/v1/flowers/observations/{id})
5. Deleting observation (DELETE /api/v1/flowers/observations/{id})
6. Anonymous identity association and anti-IDOR isolation
7. 404 on nonexistent flower reference
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_observation_with_flower_id_success(client: AsyncClient):
    """Recording an observation with flower_id returns 201."""
    payload = {
        "flower_id": "hibiscus",
        "district": "Zomba",
        "note": "Spotted near the botanical garden gate.",
        "is_demo": False,
    }
    response = await client.post("/api/v1/flowers/observations", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["flower_id"] == "hibiscus"
    assert data["plant_id"] == "hibiscus"
    assert data["district"] == "Zomba"
    assert data["note"] == "Spotted near the botanical garden gate."
    assert data["is_demo"] is False
    assert "id" in data
    assert "created_at" in data
    assert "createdAt" in data


@pytest.mark.asyncio
async def test_create_observation_with_legacy_plant_id_success(client: AsyncClient):
    """Recording an observation using Flutter Discovery.plantId returns 201."""
    payload = {
        "plant_id": "marigold",
        "district": "Lilongwe",
        "note": "Bright orange flower heads in local garden.",
        "photo": "/data/user/0/mw.flora/files/floramw_12345.jpg",
    }
    response = await client.post("/api/v1/observations", json=payload)
    assert response.status_code == 201
    data = response.json()

    assert data["flower_id"] == "marigold"
    assert data["plant_id"] == "marigold"
    assert data["district"] == "Lilongwe"
    assert data["photo_path"] == "/data/user/0/mw.flora/files/floramw_12345.jpg"
    assert data["photo"] == "/data/user/0/mw.flora/files/floramw_12345.jpg"


@pytest.mark.asyncio
async def test_create_observation_invalid_flower_returns_404(client: AsyncClient):
    """Attempting to observe a non-existent flower returns 404."""
    payload = {
        "flower_id": "nonexistent-species",
        "note": "Test note",
    }
    response = await client.post("/api/v1/flowers/observations", json=payload)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_observation_lifecycle(client: AsyncClient):
    """Test create, read, update, and delete workflow."""
    # 1. Create
    create_resp = await client.post(
        "/api/v1/flowers/observations",
        json={"flower_id": "periwinkle", "note": "Initial note"},
    )
    assert create_resp.status_code == 201
    obs_id = create_resp.json()["id"]

    # 2. Get
    get_resp = await client.get(f"/api/v1/flowers/observations/{obs_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["note"] == "Initial note"

    # 3. Patch
    patch_resp = await client.patch(
        f"/api/v1/flowers/observations/{obs_id}",
        json={"note": "Updated field note with more details", "district": "Blantyre"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["note"] == "Updated field note with more details"
    assert patch_resp.json()["district"] == "Blantyre"

    # 4. List
    list_resp = await client.get("/api/v1/flowers/observations")
    assert list_resp.status_code == 200
    assert any(item["id"] == obs_id for item in list_resp.json()["items"])

    # 5. Delete
    del_resp = await client.delete(f"/api/v1/flowers/observations/{obs_id}")
    assert del_resp.status_code == 204

    # 6. Verify deleted
    get_again = await client.get(f"/api/v1/flowers/observations/{obs_id}")
    assert get_again.status_code == 404


@pytest.mark.asyncio
async def test_observation_user_ownership_isolation(client: AsyncClient):
    """Authenticated user sees their own observations and cannot access another user's."""
    # Obtain token for User A
    auth_a = await client.post("/api/v1/auth/anonymous")
    token_a = auth_a.json()["device_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Obtain token for User B
    auth_b = await client.post("/api/v1/auth/anonymous")
    token_b = auth_b.json()["device_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates observation
    res_a = await client.post(
        "/api/v1/flowers/observations",
        json={"flower_id": "hibiscus", "note": "User A observation"},
        headers=headers_a,
    )
    assert res_a.status_code == 201
    obs_a_id = res_a.json()["id"]

    # User A can fetch it
    res_a_fetch = await client.get(
        f"/api/v1/flowers/observations/{obs_a_id}",
        headers=headers_a,
    )
    assert res_a_fetch.status_code == 200

    # User B querying User A's observation receives 404 (anti-IDOR)
    res_b_fetch = await client.get(
        f"/api/v1/flowers/observations/{obs_a_id}",
        headers=headers_b,
    )
    assert res_b_fetch.status_code == 404
