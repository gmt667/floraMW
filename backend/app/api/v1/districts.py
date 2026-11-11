"""District endpoints.

Serves the 28 administrative districts of Malawi, grouped and filterable by
region (Northern, Central, Southern), matching lib/locale_data.dart.
"""

from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.models.district import District
from app.schemas.district import DistrictOut, DistrictListResponse

router = APIRouter(prefix="/districts", tags=["Districts"])


@router.get(
    "",
    response_model=DistrictListResponse,
    summary="List Malawi administrative districts",
)
async def list_districts(
    region: Optional[str] = Query(
        None,
        description="Filter by region name: 'Northern', 'Central' or 'Southern'",
    ),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve administrative districts of Malawi.

    - Without `region`: returns all 28 districts.
    - With `region=Northern|Central|Southern`: returns that region's districts.

    Matches the regional grouping in lib/locale_data.dart:
    Northern (6), Central (9), Southern (13).
    """
    stmt = select(District).order_by(District.region.asc(), District.name.asc())

    if region and region.strip():
        stmt = stmt.where(District.region == region.strip())

    result = await db.execute(stmt)
    districts = result.scalars().all()

    # Build by_region map from results (or all regions if unfiltered)
    by_region: Dict[str, List[str]] = {"Northern": [], "Central": [], "Southern": []}
    for d in districts:
        if d.region in by_region:
            by_region[d.region].append(d.name)

    # Remove empty regions from the map when filtering
    if region and region.strip():
        by_region = {k: v for k, v in by_region.items() if v}

    return DistrictListResponse(
        total=len(districts),
        items=[DistrictOut.model_validate(d) for d in districts],
        by_region=by_region,
    )


@router.get(
    "/{district_id}",
    response_model=DistrictOut,
    summary="Get single district by ID",
)
async def get_district(district_id: int, db: AsyncSession = Depends(get_db)):
    """Retrieve details for a single administrative district by its integer ID."""
    stmt = select(District).where(District.id == district_id)
    result = await db.execute(stmt)
    district = result.scalar_one_or_none()
    if not district:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"District with ID {district_id} not found.",
        )
    return DistrictOut.model_validate(district)
