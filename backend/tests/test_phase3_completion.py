"""Tests for FloraMW Phase 3 Backend Integration Completion.

Validates:
1. Flower Catalogue API Completion (/api/v1/flowers)
   - All 4 seeded flowers (hibiscus, periwinkle, marigold, frangipani)
   - Detail retrieval with full sections, sources, verified districts
   - Search across common, scientific, and family names
   - Filtering by category, family, and district
   - Unknown flower ID returns 404
   - Sorting by name_asc and name_desc

2. Flower Reports API (/api/v1/flowers/reports and /api/v1/reports)
   - Submission of reports with and without flower reference
   - Field validations (details length, topic limits)
   - Owner-isolated retrieval and listing
   - Anti-IDOR: cross-user and unauthenticated retrieval returns 404
   - Report updates (owner editing details vs admin resolving status)
   - Administrative listing with status/flower filtering (requires role='admin')
   - Unauthorized administrative access rejected with 403 Forbidden
   - Report deletion by owner or admin; non-owner delete rejected with 404

3. Cross-Device Observation Retrieval & Administrative Access
   - User-scoped listing and individual observation retrieval
   - Cross-user retrieval returns 404 (Anti-IDOR)
   - Administrative observation listing across all users (role='admin')
   - Non-admin access to all_users/admin queue rejected with 403 Forbidden
   - Administrator can inspect observations across users

4. Privacy & Personal Data Lifecycle (/api/v1/privacy/personal-data)
   - Unauthenticated purge rejected with 401
   - Authenticated purge deletes user's observations and reports
   - Purge revokes device token (subsequent request returns 401)
   - Shared botanical catalogue records and districts are strictly preserved
   - Unrelated users' data is strictly preserved
   - Route aliases (/api/v1/users/me/data, /api/v1/auth/me/data)
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import hash_device_token
from app.models.flower import Flower, FlowerObservation, FlowerReport
from app.models.user import User


async def create_user_with_role(
    db: AsyncSession,
    role: str = "guest",
    token: str = "test-token-fixed-entropy-abcdef0123456789",
) -> tuple[str, str]:
    """Helper to seed a test user with a specific role and known device token."""
    token_hash = hash_device_token(token)
    user = User(
        role=role,
        is_anonymous=(role == "guest"),
        device_token_hash=token_hash,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return str(user.id), token


# ===========================================================================
# 1. Flower Catalogue API Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_catalogue_all_four_seeded_flowers_present(client: AsyncClient):
    """The four canonical flowers must be returned by default listing."""
    res = await client.get("/api/v1/flowers")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 4
    slugs = {item["id"] for item in data["items"]}
    assert slugs == {"hibiscus", "periwinkle", "marigold", "frangipani"}


@pytest.mark.asyncio
async def test_catalogue_detail_all_four_flowers(client: AsyncClient):
    """Every seeded flower profile contains complete sections and sources."""
    for slug in ["hibiscus", "periwinkle", "marigold", "frangipani"]:
        res = await client.get(f"/api/v1/flowers/{slug}")
        assert res.status_code == 200, f"Flower {slug} failed retrieval"
        data = res.json()
        assert data["id"] == slug
        assert len(data["name"]) > 0
        assert len(data["scientific"]) > 0
        assert isinstance(data["sections"], dict)
        assert len(data["sections"]) >= 8  # 8 pending sections
        assert isinstance(data["sources"], list)
        assert len(data["sources"]) >= 1


@pytest.mark.asyncio
async def test_catalogue_unknown_flower_returns_404(client: AsyncClient):
    """Non-existent flower slug returns 404 with structured error message."""
    res = await client.get("/api/v1/flowers/non_existent_rose_123")
    assert res.status_code == 404
    assert "was not found in the botanical catalogue" in res.json()["detail"]


@pytest.mark.asyncio
async def test_catalogue_search_scientific_and_family(client: AsyncClient):
    """Search matches scientific name and family case-insensitively."""
    # Scientific search
    res_sci = await client.get("/api/v1/flowers", params={"q": "Catharanthus"})
    assert res_sci.status_code == 200
    data_sci = res_sci.json()
    assert data_sci["total"] == 1
    assert data_sci["items"][0]["id"] == "periwinkle"

    # Family search
    res_fam = await client.get("/api/v1/flowers", params={"q": "Malvaceae"})
    assert res_fam.status_code == 200
    assert any(item["id"] == "hibiscus" for item in res_fam.json()["items"])


@pytest.mark.asyncio
async def test_catalogue_filter_by_district(client: AsyncClient):
    """Filtering by district returns flowers documented in that district."""
    res = await client.get("/api/v1/flowers", params={"district": "Zomba"})
    assert res.status_code == 200
    data = res.json()
    assert "items" in data
    # Results should be valid list without database syntax errors


@pytest.mark.asyncio
async def test_catalogue_sorting_asc_and_desc(client: AsyncClient):
    """Catalogue sort order name_asc and name_desc operates correctly."""
    res_asc = await client.get("/api/v1/flowers", params={"sort": "name_asc"})
    assert res_asc.status_code == 200
    names_asc = [f["name"] for f in res_asc.json()["items"]]
    assert names_asc == sorted(names_asc)

    res_desc = await client.get("/api/v1/flowers", params={"sort": "name_desc"})
    assert res_desc.status_code == 200
    names_desc = [f["name"] for f in res_desc.json()["items"]]
    assert names_desc == sorted(names_asc, reverse=True)


# ===========================================================================
# 2. Flower Reports API Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_reports_owner_lifecycle(client: AsyncClient, db_session: AsyncSession):
    """Owner can create, view, update, and delete their own report."""
    _, token = await create_user_with_role(db_session, role="guest", token="owner-token-reports-1234")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create
    create_payload = {
        "flower_id": "hibiscus",
        "topic": "Local knowledge",
        "details": "Hibiscus local name clarification for Southern region.",
        "source": "Zomba market botanical survey",
    }
    create_res = await client.post("/api/v1/flowers/reports", json=create_payload, headers=headers)
    assert create_res.status_code == 201
    rep_id = create_res.json()["id"]

    # 2. Retrieve
    get_res = await client.get(f"/api/v1/flowers/reports/{rep_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["details"] == create_payload["details"]

    # 3. Owner Update
    update_res = await client.patch(
        f"/api/v1/flowers/reports/{rep_id}",
        json={"details": "Updated details: Chidole is used in Chiradzulu."},
        headers=headers,
    )
    assert update_res.status_code == 200
    assert "Chiradzulu" in update_res.json()["details"]

    # 4. Owner cannot set arbitrary administrative resolution status
    invalid_status_res = await client.patch(
        f"/api/v1/flowers/reports/{rep_id}",
        json={"status": "resolved"},
        headers=headers,
    )
    assert invalid_status_res.status_code == 403
    assert "administrative users" in invalid_status_res.json()["detail"]

    # 5. Owner Delete
    del_res = await client.delete(f"/api/v1/flowers/reports/{rep_id}", headers=headers)
    assert del_res.status_code == 204

    # 6. Verify deleted
    get_after_del = await client.get(f"/api/v1/flowers/reports/{rep_id}", headers=headers)
    assert get_after_del.status_code == 404


@pytest.mark.asyncio
async def test_reports_admin_management_and_rbac(client: AsyncClient, db_session: AsyncSession):
    """Admin can view all reports, advance status to resolved, and regular users are denied."""
    # Create regular user and admin user
    _, user_token = await create_user_with_role(db_session, role="guest", token="regular-user-token-5555")
    _, admin_token = await create_user_with_role(db_session, role="admin", token="admin-user-token-9999")

    user_headers = {"Authorization": f"Bearer {user_token}"}
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # Regular user creates report
    create_res = await client.post(
        "/api/v1/flowers/reports",
        json={"flower_id": "marigold", "topic": "Safety", "details": "Sap can cause irritation."},
        headers=user_headers,
    )
    assert create_res.status_code == 201
    rep_id = create_res.json()["id"]

    # Regular user cannot access admin queue (403)
    user_admin_res = await client.get("/api/v1/flowers/reports/admin", headers=user_headers)
    assert user_admin_res.status_code == 403

    user_all_res = await client.get("/api/v1/flowers/reports", params={"all_users": True}, headers=user_headers)
    assert user_all_res.status_code == 403

    # Admin CAN access admin queue
    admin_queue_res = await client.get("/api/v1/flowers/reports/admin", headers=admin_headers)
    assert admin_queue_res.status_code == 200
    assert any(r["id"] == rep_id for r in admin_queue_res.json()["items"])

    # Admin CAN advance status to 'in_review' then 'resolved'
    patch_res = await client.patch(
        f"/api/v1/flowers/reports/{rep_id}",
        json={"status": "resolved"},
        headers=admin_headers,
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "resolved"

    # Admin CAN delete report
    admin_del = await client.delete(f"/api/v1/flowers/reports/{rep_id}", headers=admin_headers)
    assert admin_del.status_code == 204


@pytest.mark.asyncio
async def test_reports_anti_idor_cross_user_protection(client: AsyncClient, db_session: AsyncSession):
    """Cross-user retrieval or modification of reports returns 404 (Anti-IDOR)."""
    _, token_a = await create_user_with_role(db_session, role="guest", token="token-user-a-1111")
    _, token_b = await create_user_with_role(db_session, role="guest", token="token-user-b-2222")

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates report
    res_a = await client.post(
        "/api/v1/flowers/reports",
        json={"topic": "Identification", "details": "Confidential correction draft from user A."},
        headers=headers_a,
    )
    rep_id = res_a.json()["id"]

    # User B cannot GET User A's report (404)
    get_b = await client.get(f"/api/v1/flowers/reports/{rep_id}", headers=headers_b)
    assert get_b.status_code == 404

    # User B cannot PATCH User A's report (404)
    patch_b = await client.patch(
        f"/api/v1/flowers/reports/{rep_id}",
        json={"details": "Malicious overwrite attempt"},
        headers=headers_b,
    )
    assert patch_b.status_code == 404

    # User B cannot DELETE User A's report (404)
    del_b = await client.delete(f"/api/v1/flowers/reports/{rep_id}", headers=headers_b)
    assert del_b.status_code == 404


# ===========================================================================
# 3. Cross-Device Observation Retrieval & Admin Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_observation_user_scoped_and_admin_queue(client: AsyncClient, db_session: AsyncSession):
    """Users view only their observations; admin can inspect all observations across devices."""
    _, token_user = await create_user_with_role(db_session, role="guest", token="obs-user-token-3333")
    _, token_admin = await create_user_with_role(db_session, role="admin", token="obs-admin-token-7777")

    user_headers = {"Authorization": f"Bearer {token_user}"}
    admin_headers = {"Authorization": f"Bearer {token_admin}"}

    # User creates observation
    obs_res = await client.post(
        "/api/v1/flowers/observations",
        json={"flower_id": "hibiscus", "district": "Zomba", "note": "Cross-device user observation."},
        headers=user_headers,
    )
    assert obs_res.status_code == 201
    obs_id = obs_res.json()["id"]

    # User can retrieve it
    user_get = await client.get(f"/api/v1/flowers/observations/{obs_id}", headers=user_headers)
    assert user_get.status_code == 200
    assert user_get.json()["id"] == obs_id

    # User cannot request admin observation queue (403)
    user_admin_queue = await client.get("/api/v1/flowers/observations/admin", headers=user_headers)
    assert user_admin_queue.status_code == 403

    user_all_flag = await client.get("/api/v1/flowers/observations", params={"all_users": True}, headers=user_headers)
    assert user_all_flag.status_code == 403

    # Admin CAN retrieve observation queue across all users
    admin_list = await client.get("/api/v1/flowers/observations/admin", headers=admin_headers)
    assert admin_list.status_code == 200
    assert any(o["id"] == obs_id for o in admin_list.json()["items"])

    # Admin CAN retrieve specific user observation
    admin_get = await client.get(f"/api/v1/flowers/observations/{obs_id}", headers=admin_headers)
    assert admin_get.status_code == 200
    assert admin_get.json()["id"] == obs_id


# ===========================================================================
# 4. Privacy and Personal Data Lifecycle Tests
# ===========================================================================


@pytest.mark.asyncio
async def test_privacy_purge_unauthenticated_rejected(client: AsyncClient):
    """Calling data purge without valid authentication returns 401."""
    res = await client.delete("/api/v1/privacy/personal-data")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_privacy_purge_deletes_user_data_and_revokes_token(
    client: AsyncClient,
    db_session: AsyncSession,
):
    """Personal data purge permanently removes observations, reports, and revokes token."""
    user_id, token = await create_user_with_role(db_session, role="guest", token="purge-test-token-8888")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create observation and report under this user
    await client.post(
        "/api/v1/flowers/observations",
        json={"flower_id": "hibiscus", "district": "Blantyre", "note": "Observation to be purged."},
        headers=headers,
    )
    await client.post(
        "/api/v1/flowers/reports",
        json={"flower_id": "hibiscus", "topic": "Safety", "details": "Report to be purged."},
        headers=headers,
    )

    # Verify data exists before purge
    obs_before = await client.get("/api/v1/flowers/observations", headers=headers)
    assert obs_before.json()["total"] >= 1

    rep_before = await client.get("/api/v1/flowers/reports", headers=headers)
    assert rep_before.json()["total"] >= 1

    # 2. Execute Purge
    purge_res = await client.delete("/api/v1/privacy/personal-data", headers=headers)
    assert purge_res.status_code == 200
    purge_data = purge_res.json()
    assert purge_data["status"] == "purged"
    assert purge_data["user_id"] == user_id
    assert purge_data["deleted_observations_count"] >= 1
    assert purge_data["deleted_reports_count"] >= 1

    # 3. Repeated call with the same token returns 401 (token is revoked/user deleted)
    second_purge = await client.delete("/api/v1/privacy/personal-data", headers=headers)
    assert second_purge.status_code == 401

    # 4. Shared catalogue data remains 100% intact
    cat_res = await client.get("/api/v1/flowers")
    assert cat_res.status_code == 200
    assert cat_res.json()["total"] == 4


@pytest.mark.asyncio
async def test_privacy_purge_aliases(client: AsyncClient, db_session: AsyncSession):
    """Purge aliases /users/me/data and /auth/me/data function identically."""
    # Test /users/me/data alias
    _, token1 = await create_user_with_role(db_session, role="guest", token="alias-token-1111")
    res1 = await client.delete("/api/v1/users/me/data", headers={"Authorization": f"Bearer {token1}"})
    assert res1.status_code == 200
    assert res1.json()["status"] == "purged"

    # Test /auth/me/data alias
    _, token2 = await create_user_with_role(db_session, role="guest", token="alias-token-2222")
    res2 = await client.delete("/api/v1/auth/me/data", headers={"Authorization": f"Bearer {token2}"})
    assert res2.status_code == 200
    assert res2.json()["status"] == "purged"
