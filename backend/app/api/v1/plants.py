"""Plant catalog endpoints (Backward compatibility alias).

Delegates to canonical Flower catalogue handlers while serving /api/v1/plants routes.
"""

from typing import Literal, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.flower import PlantDetailOut, PlantListResponse
from app.api.v1.flowers import list_flowers as _list_flowers, get_flower as _get_flower

router = APIRouter(prefix="/plants", tags=["Botanical Catalog"])


@router.get(
    "",
    response_model=PlantListResponse,
    summary="Browse and search botanical reference catalog (Legacy plant route)",
)
async def list_plants(
    q: Optional[str] = Query(
        None,
        description="Search common name, scientific name or family",
        max_length=100,
    ),
    category: Optional[str] = Query(
        None,
        description="Filter by category (e.g. 'Garden flowers')",
        max_length=50,
    ),
    family: Optional[str] = Query(
        None,
        description="Filter by botanical family (e.g. 'Apocynaceae')",
        max_length=100,
    ),
    district: Optional[str] = Query(
        None,
        description="Filter by Malawian district name (e.g. 'Zomba')",
        max_length=100,
    ),
    sort: Literal["name_asc", "name_desc"] = Query(
        "name_asc",
        description=(
            "Sort order: 'name_asc' (A to Z, default) or 'name_desc' (Z to A). "
            "Unsupported values are rejected with HTTP 422."
        ),
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """Legacy alias for GET /api/v1/flowers."""
    return await _list_flowers(
        q=q,
        category=category,
        family=family,
        district=district,
        sort=sort,
        page=page,
        limit=limit,
        db=db,
    )


@router.get(
    "/{plant_id}",
    response_model=PlantDetailOut,
    summary="Get plant profile by unique identifier (Legacy plant route)",
)
async def get_plant(
    plant_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Legacy alias for GET /api/v1/flowers/{flower_id}."""
    return await _get_flower(flower_id=plant_id, db=db)
