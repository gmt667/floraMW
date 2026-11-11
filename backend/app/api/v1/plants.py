"""Plant catalog endpoints.

Serves the public botanical reference catalog with search, category filtering,
and pagination. All data matches the frontend contract in lib/models.dart.
"""

from math import ceil
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.plant import Plant, PlantDistribution
from app.schemas.plant import (
    PlantSummaryOut,
    PlantDetailOut,
    PlantSourceOut,
    PlantSectionOut,
    PlantListResponse,
)

router = APIRouter(prefix="/plants", tags=["Botanical Catalog"])


@router.get(
    "",
    response_model=PlantListResponse,
    summary="Browse and search botanical reference catalog",
)
async def list_plants(
    q: Optional[str] = Query(
        None, description="Search common name, scientific name or family"
    ),
    category: Optional[str] = Query(
        None, description="Filter by category (e.g. 'Garden flowers')"
    ),
    sort: Optional[str] = Query(
        "name_asc", description="Sort order: 'name_asc' or 'name_desc'"
    ),
    page: int = Query(1, ge=1, description="Page number (1-based)"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve paginated plant profiles from the reference catalog.

    Supports full-text search across common name, scientific name and family.
    Category filtering maps to the frontend plant.category field.
    """
    stmt = select(Plant).where(Plant.is_published.is_(True))

    if q and q.strip():
        search = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Plant.common_name_en).like(search),
                func.lower(Plant.scientific_name).like(search),
                func.lower(Plant.family).like(search),
            )
        )

    if category and category.strip() and category.strip().lower() != "all plants":
        stmt = stmt.where(Plant.category == category.strip())

    # Count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Sort
    if sort == "name_desc":
        stmt = stmt.order_by(Plant.common_name_en.desc())
    else:
        stmt = stmt.order_by(Plant.common_name_en.asc())

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)

    plants = (await db.execute(stmt)).scalars().all()

    total_pages = ceil(total / limit) if total > 0 else 1
    has_more = (page * limit) < total

    items = [
        PlantSummaryOut(
            id=p.id,
            name=p.common_name_en,
            scientific=p.scientific_name,
            family=p.family,
            category=p.category,
            symbol=p.symbol,
            description=p.description,
            photo_asset=f"assets/plants/{p.id}.jpg",
        )
        for p in plants
    ]

    return PlantListResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_more=has_more,
        items=items,
    )


@router.get(
    "/{plant_id}",
    response_model=PlantDetailOut,
    summary="Get full botanical profile by plant ID",
)
async def get_plant(plant_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve a complete botanical reference profile by stable slug ID.

    Returns:
    - Core taxonomy matching frontend Plant model fields
    - sections: Map<String, String> of botanical profile sections
    - sources: List<PlantSource> with title and url (matches lib/models.dart)
    - verified_districts: districts with confirmed occurrence
    """
    stmt = (
        select(Plant)
        .where(Plant.id == plant_id, Plant.is_published.is_(True))
        .options(
            selectinload(Plant.sections),
            selectinload(Plant.sources),
            selectinload(Plant.distributions).selectinload(PlantDistribution.district),
        )
    )
    result = await db.execute(stmt)
    plant = result.scalar_one_or_none()

    if not plant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plant '{plant_id}' not found.",
        )

    # Reconstruct Map<String, String> matching frontend sections contract
    sections_map = {s.section_key: s.content for s in plant.sections}

    section_details = [
        PlantSectionOut(
            section_key=s.section_key,
            content=s.content,
            verification_status=s.verification_status,
            content_disclaimer_type=s.content_disclaimer_type,
            source_citation=s.source_citation,
        )
        for s in plant.sections
    ]

    # title/url matches frontend PlantSource(this.title, this.url)
    sources_list = [
        PlantSourceOut(
            title=s.title,
            url=s.url,
            is_pmra_reference=s.is_pmra_reference,
        )
        for s in plant.sources
    ]

    verified_districts = [
        d.district.name
        for d in plant.distributions
        if d.is_verified and d.district
    ]

    return PlantDetailOut(
        id=plant.id,
        name=plant.common_name_en,
        scientific=plant.scientific_name,
        family=plant.family,
        category=plant.category,
        symbol=plant.symbol,
        description=plant.description,
        photo_asset=f"assets/plants/{plant.id}.jpg",
        sections=sections_map,
        section_details=section_details,
        sources=sources_list,
        verified_districts=verified_districts,
    )
