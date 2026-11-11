"""Tests for Botanical Catalog (Plant) endpoints.

All expected IDs, names, categories and section keys are sourced directly
from lib/models.dart — no invented data.

Actual frontend plants: hibiscus, periwinkle, marigold, frangipani.
Section keys: the 8 'pending' keys from lib/models.dart plus 'Identifying features'.
PlantSource fields: title, url  (matches Dart PlantSource(this.title, this.url)).
"""

import pytest
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Ground truth from lib/models.dart
# ---------------------------------------------------------------------------
FRONTEND_PLANTS = [
    {"id": "hibiscus", "name": "Chinese hibiscus", "category": "Garden flowers",
     "scientific": "Hibiscus rosa-sinensis", "family": "Malvaceae"},
    {"id": "periwinkle", "name": "Madagascar periwinkle", "category": "Research interest",
     "scientific": "Catharanthus roseus", "family": "Apocynaceae"},
    {"id": "marigold", "name": "African marigold", "category": "Garden flowers",
     "scientific": "Tagetes erecta", "family": "Asteraceae"},
    {"id": "frangipani", "name": "Frangipani", "category": "Flowering trees",
     "scientific": "Plumeria rubra", "family": "Apocynaceae"},
]

# 8 pending keys from lib/models.dart const pending + 'Identifying features'
KNOWN_SECTION_KEYS = {
    "Local names & knowledge",
    "Medicinal research",
    "Malawi distribution",
    "Growing conditions",
    "Plant care & treatment",
    "Effects & precautions",
    "Legal & conservation",
    "Sources & review",
    "Identifying features",
}


# ---------------------------------------------------------------------------
# Catalog list tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_plants_default_returns_all_four(client: AsyncClient):
    """Default list returns the 4 seeded plants matching the frontend catalogue."""
    response = await client.get("/api/v1/plants")
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 4
    assert len(data["items"]) == 4
    assert data["page"] == 1
    assert data["limit"] == 20
    assert data["has_more"] is False
    assert data["total_pages"] == 1

    # Verify required summary fields
    for item in data["items"]:
        for field in ("id", "name", "scientific", "family", "category", "description", "photo_asset"):
            assert field in item, f"Missing field '{field}' in list item"


@pytest.mark.asyncio
async def test_list_plants_expected_ids_present(client: AsyncClient):
    """All four frontend plant IDs must be present in the catalog response."""
    data = (await client.get("/api/v1/plants")).json()
    returned_ids = {p["id"] for p in data["items"]}
    expected_ids = {p["id"] for p in FRONTEND_PLANTS}
    assert returned_ids == expected_ids


@pytest.mark.asyncio
async def test_list_plants_pagination_limit(client: AsyncClient):
    """Pagination with limit=2 returns 2 items and has_more=True."""
    resp = await client.get("/api/v1/plants", params={"page": 1, "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    assert len(data["items"]) == 2
    assert data["limit"] == 2
    assert data["has_more"] is True
    assert data["total_pages"] == 2


@pytest.mark.asyncio
async def test_list_plants_pagination_page_2(client: AsyncClient):
    """Page 2 with limit=2 returns remaining 2 items and has_more=False."""
    resp = await client.get("/api/v1/plants", params={"page": 2, "limit": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2
    assert data["has_more"] is False

    # Pages 1 and 2 together cover all 4 unique plants
    p1_ids = {p["id"] for p in (await client.get("/api/v1/plants", params={"page": 1, "limit": 2})).json()["items"]}
    p2_ids = {p["id"] for p in data["items"]}
    assert len(p1_ids | p2_ids) == 4
    assert p1_ids.isdisjoint(p2_ids)


@pytest.mark.asyncio
async def test_list_plants_category_garden_flowers(client: AsyncClient):
    """Category filter 'Garden flowers' returns hibiscus and marigold only."""
    resp = await client.get("/api/v1/plants", params={"category": "Garden flowers"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2
    ids = {p["id"] for p in data["items"]}
    assert ids == {"hibiscus", "marigold"}
    assert all(p["category"] == "Garden flowers" for p in data["items"])


@pytest.mark.asyncio
async def test_list_plants_category_flowering_trees(client: AsyncClient):
    """Category filter 'Flowering trees' returns frangipani only."""
    resp = await client.get("/api/v1/plants", params={"category": "Flowering trees"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "frangipani"


@pytest.mark.asyncio
async def test_list_plants_category_research_interest(client: AsyncClient):
    """Category filter 'Research interest' returns periwinkle only."""
    resp = await client.get("/api/v1/plants", params={"category": "Research interest"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == "periwinkle"


@pytest.mark.asyncio
async def test_list_plants_search_by_common_name(client: AsyncClient):
    """Search by common name returns matching plant."""
    resp = await client.get("/api/v1/plants", params={"q": "Frangipani"})
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["id"] == "frangipani" for p in data["items"])


@pytest.mark.asyncio
async def test_list_plants_search_by_scientific_name(client: AsyncClient):
    """Search by partial scientific name returns matching plant."""
    resp = await client.get("/api/v1/plants", params={"q": "Catharanthus"})
    assert resp.status_code == 200
    data = resp.json()
    assert any(p["id"] == "periwinkle" for p in data["items"])


@pytest.mark.asyncio
async def test_list_plants_search_by_family(client: AsyncClient):
    """Search by family name returns matching plants."""
    resp = await client.get("/api/v1/plants", params={"q": "Apocynaceae"})
    assert resp.status_code == 200
    data = resp.json()
    ids = {p["id"] for p in data["items"]}
    assert "periwinkle" in ids
    assert "frangipani" in ids


@pytest.mark.asyncio
async def test_list_plants_search_no_match_returns_empty(client: AsyncClient):
    """Search with no matches returns total=0 and empty items."""
    resp = await client.get("/api/v1/plants", params={"q": "xyzzy_nonexistent_plant"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["items"] == []
    assert data["has_more"] is False


@pytest.mark.asyncio
async def test_list_plants_all_plants_category_alias(client: AsyncClient):
    """Category 'All plants' is treated as no filter — returns all 4."""
    resp = await client.get("/api/v1/plants", params={"category": "All plants"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 4


# ---------------------------------------------------------------------------
# Plant detail tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("plant", FRONTEND_PLANTS)
async def test_get_plant_detail_all_plants(plant, client: AsyncClient):
    """Every seeded plant returns a valid detailed profile."""
    resp = await client.get(f"/api/v1/plants/{plant['id']}")
    assert resp.status_code == 200, f"Failed for {plant['id']}: {resp.text}"

    p = resp.json()
    assert p["id"] == plant["id"]
    assert p["name"] == plant["name"]
    assert p["scientific"] == plant["scientific"]
    assert p["family"] == plant["family"]
    assert p["category"] == plant["category"]
    assert len(p["description"]) > 0

    # photo_asset must follow frontend convention: assets/plants/{id}.jpg
    assert p["photo_asset"] == f"assets/plants/{plant['id']}.jpg"


@pytest.mark.asyncio
async def test_get_plant_detail_sections_map(client: AsyncClient):
    """Plant detail sections must be a dict (Map<String,String>) with known keys."""
    resp = await client.get("/api/v1/plants/hibiscus")
    assert resp.status_code == 200
    p = resp.json()

    sections = p["sections"]
    assert isinstance(sections, dict)
    assert len(sections) > 0

    # All returned keys must be from the known frontend section key set
    for key in sections:
        assert key in KNOWN_SECTION_KEYS, f"Unexpected section key: '{key}'"

    # hibiscus must have 'Identifying features'
    assert "Identifying features" in sections
    assert len(sections["Identifying features"]) > 0


@pytest.mark.asyncio
async def test_get_plant_detail_sources_field_names(client: AsyncClient):
    """Sources must have 'title' and 'url' — matching frontend PlantSource(title, url)."""
    resp = await client.get("/api/v1/plants/hibiscus")
    assert resp.status_code == 200
    sources = resp.json()["sources"]

    assert len(sources) >= 1
    for source in sources:
        assert "title" in source, "Missing 'title' field — frontend uses PlantSource(title, url)"
        assert "url" in source, "Missing 'url' field"
        assert isinstance(source["title"], str)
        assert isinstance(source["url"], str)
        # label must NOT be present (backend previously had this wrong)
        assert "label" not in source, "Unexpected 'label' field — frontend contract uses 'title'"


@pytest.mark.asyncio
async def test_get_plant_detail_pmra_source(client: AsyncClient):
    """Every plant must include the PMRA source reference."""
    for plant in FRONTEND_PLANTS:
        resp = await client.get(f"/api/v1/plants/{plant['id']}")
        sources = resp.json()["sources"]
        pmra_sources = [s for s in sources if s.get("is_pmra_reference") is True]
        assert len(pmra_sources) >= 1, f"Plant '{plant['id']}' missing PMRA source"
        pmra = pmra_sources[0]
        assert "pmra.mw" in pmra["url"]


@pytest.mark.asyncio
async def test_get_plant_not_found(client: AsyncClient):
    """Unknown plant ID returns 404 with detail message."""
    resp = await client.get("/api/v1/plants/royal-fern-does-not-exist")
    assert resp.status_code == 404
    assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# F-2: sort parameter validation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_plants_sort_name_asc_order(client: AsyncClient):
    """sort=name_asc returns plants in ascending alphabetical order by common name."""
    resp = await client.get("/api/v1/plants", params={"sort": "name_asc"})
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["items"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_plants_sort_name_desc_order(client: AsyncClient):
    """sort=name_desc returns plants in descending alphabetical order by common name."""
    resp = await client.get("/api/v1/plants", params={"sort": "name_desc"})
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["items"]]
    assert names == sorted(names, reverse=True)


@pytest.mark.asyncio
async def test_list_plants_sort_omitted_defaults_to_name_asc(client: AsyncClient):
    """Omitting sort defaults to name_asc (alphabetical A to Z)."""
    resp = await client.get("/api/v1/plants")
    assert resp.status_code == 200
    names = [p["name"] for p in resp.json()["items"]]
    assert names == sorted(names)


@pytest.mark.asyncio
async def test_list_plants_invalid_sort_returns_422(client: AsyncClient):
    """Unsupported sort value is rejected with HTTP 422."""
    resp = await client.get("/api/v1/plants", params={"sort": "alphabetical"})
    assert resp.status_code == 422
