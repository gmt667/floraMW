"""Tests for botanical correction and feedback report endpoints.

Covers:
1. Submitting a report with flower_id (POST /api/v1/flowers/reports and /reports)
2. Submitting a general report without flower_id
3. Validation of topic and details length
4. Listing reports
5. Duplicate report ID rejection (409)
6. Dual source and source_reference support
7. CamelCase payload support matching Flutter ReportScreen
8. Report retrieval by ID (GET /api/v1/flowers/reports/{id})
9. Anti-IDOR ownership isolation between users and unauthenticated callers
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
    assert data["source_reference"] == "Zomba herbalist consultation"
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
    await client.post(
        "/api/v1/flowers/reports",
        json={"topic": "Test topic", "details": "Some test details for listing"},
    )
    response = await client.get("/api/v1/flowers/reports")
    assert response.status_code == 200
    assert response.json()["total"] >= 1


@pytest.mark.asyncio
async def test_create_report_duplicate_id_returns_409(client: AsyncClient):
    """Submitting a report with an already existing ID returns 409 Conflict."""
    custom_id = "test-dup-report-id-12345"
    payload = {
        "id": custom_id,
        "topic": "Duplicate test",
        "details": "First submission with custom ID.",
    }
    res1 = await client.post("/api/v1/flowers/reports", json=payload)
    assert res1.status_code == 201

    # Second submission with exact same ID
    res2 = await client.post("/api/v1/flowers/reports", json=payload)
    assert res2.status_code == 409
    assert "already exists" in res2.json()["detail"]


@pytest.mark.asyncio
async def test_report_source_reference_alias(client: AsyncClient):
    """Payload using source_reference or sourceReference populates source cleanly."""
    payload = {
        "topic": "Reference check",
        "details": "Verifying citation alias handling in backend schema.",
        "source_reference": "NC State Extension Horticultural Leaflet",
    }
    res = await client.post("/api/v1/flowers/reports", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["source"] == "NC State Extension Horticultural Leaflet"
    assert data["source_reference"] == "NC State Extension Horticultural Leaflet"


@pytest.mark.asyncio
async def test_report_flutter_camelcase_payload(client: AsyncClient):
    """Report payload using Flutter DraftsScreen format (plantId, createdAt) succeeds."""
    payload = {
        "plantId": "marigold",
        "topic": "Local knowledge",
        "details": "Widely planted around maize perimeters as pest deterrent.",
        "source": "Farmer interviews in Dedza district",
        "createdAt": "2026-11-16T10:00:00Z",
        "status": "local-draft",
    }
    res = await client.post("/api/v1/reports", json=payload)
    assert res.status_code == 201
    data = res.json()
    assert data["flower_id"] == "marigold"
    assert data["plant_id"] == "marigold"
    assert data["source"] == "Farmer interviews in Dedza district"


@pytest.mark.asyncio
async def test_report_retrieval_and_anti_idor(client: AsyncClient):
    """User can fetch their own report; another user receives 404 (anti-IDOR)."""
    # Create two anonymous users
    auth_a = await client.post("/api/v1/auth/anonymous")
    token_a = auth_a.json()["device_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    auth_b = await client.post("/api/v1/auth/anonymous")
    token_b = auth_b.json()["device_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User A creates a report
    res_a = await client.post(
        "/api/v1/flowers/reports",
        json={
            "flower_id": "hibiscus",
            "topic": "Safety",
            "details": "Private user feedback on hibiscus care instructions.",
        },
        headers=headers_a,
    )
    assert res_a.status_code == 201
    report_id = res_a.json()["id"]

    # User A can retrieve it
    get_a = await client.get(f"/api/v1/flowers/reports/{report_id}", headers=headers_a)
    assert get_a.status_code == 200
    assert get_a.json()["id"] == report_id

    # User B receives 404 (anti-IDOR)
    get_b = await client.get(f"/api/v1/flowers/reports/{report_id}", headers=headers_b)
    assert get_b.status_code == 404

    # Unauthenticated caller receives 404
    get_anon = await client.get(f"/api/v1/flowers/reports/{report_id}")
    assert get_anon.status_code == 404

    # User A's list shows this report; User B's list does not show User A's report
    list_a = await client.get("/api/v1/flowers/reports", headers=headers_a)
    assert any(r["id"] == report_id for r in list_a.json()["items"])

    list_b = await client.get("/api/v1/flowers/reports", headers=headers_b)
    assert not any(r["id"] == report_id for r in list_b.json()["items"])
