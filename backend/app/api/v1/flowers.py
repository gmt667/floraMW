"""Canonical Flower catalogue API endpoints.

Serves the public botanical reference catalog with search, category filtering,
district filtering, and pagination.
"""

from math import ceil
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, or_
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.flower import Flower, FlowerDistribution
from app.models.district import District
from app.schemas.flower import (
    FlowerSummaryOut,
    FlowerDetailOut,
    FlowerSourceOut,
    FlowerSectionOut,
    FlowerListResponse,
)

router = APIRouter(prefix="/flowers", tags=["Flower Catalogue"])


@router.get(
    "",
    response_model=FlowerListResponse,
    summary="Browse and search botanical flower catalog",
)
async def list_flowers(
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
    """Retrieve paginated flower profiles from the botanical reference catalog.

    Supports search across common name, scientific name, and family.
    Category, family, and district filtering map directly to botanical classification fields.
    """
    stmt = select(Flower).where(Flower.is_published.is_(True))

    if q and q.strip():
        search = f"%{q.strip().lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Flower.common_name_en).like(search),
                func.lower(Flower.scientific_name).like(search),
                func.lower(Flower.family).like(search),
            )
        )

    if category and category.strip() and category.strip().lower() != "all plants":
        stmt = stmt.where(Flower.category == category.strip())

    if family and family.strip():
        stmt = stmt.where(func.lower(Flower.family) == family.strip().lower())

    if district and district.strip():
        cleaned_district = district.strip().lower()
        stmt = (
            stmt.join(Flower.distributions)
            .join(FlowerDistribution.district)
            .where(func.lower(District.name) == cleaned_district)
            .distinct()
        )

    # Count before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Sort
    if sort == "name_desc":
        stmt = stmt.order_by(Flower.common_name_en.desc())
    else:
        stmt = stmt.order_by(Flower.common_name_en.asc())

    # Paginate
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)

    flowers = (await db.execute(stmt)).scalars().all()

    total_pages = ceil(total / limit) if total > 0 else 1
    has_more = (page * limit) < total

    items = [
        FlowerSummaryOut(
            id=f.id,
            name=f.common_name_en,
            scientific=f.scientific_name,
            family=f.family,
            category=f.category,
            symbol=f.symbol,
            description=f.description,
            photo_asset=f"assets/plants/{f.id}.jpg",
        )
        for f in flowers
    ]

    return FlowerListResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_more=has_more,
        items=items,
    )


@router.get(
    "/{flower_id}",
    response_model=FlowerDetailOut,
    summary="Get flower profile by unique identifier",
)
async def get_flower(
    flower_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Retrieve complete botanical profile for a flower.

    Includes botanical sections and bibliographic sources matching the frontend Plant model.
    """
    stmt = (
        select(Flower)
        .where(Flower.id == flower_id.strip(), Flower.is_published.is_(True))
        .options(
            selectinload(Flower.sections),
            selectinload(Flower.sources),
            selectinload(Flower.distributions).selectinload(FlowerDistribution.district),
        )
    )
    result = await db.execute(stmt)
    flower = result.scalar_one_or_none()

    if not flower:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Flower '{flower_id}' was not found in the botanical catalogue.",
        )

    # Convert sections to Dict[str, str]
    sections_dict = {s.section_key: s.content for s in flower.sections}
    section_details = [
        FlowerSectionOut(
            section_key=s.section_key,
            content=s.content,
            verification_status=s.verification_status,
            content_disclaimer_type=s.content_disclaimer_type,
            source_citation=s.source_citation,
        )
        for s in flower.sections
    ]

    sources_list = [
        FlowerSourceOut(
            title=src.title,
            url=src.url,
            is_pmra_reference=src.is_pmra_reference,
        )
        for src in flower.sources
    ]

    verified_districts = [
        dist.district.name for dist in flower.distributions if dist.is_verified and dist.district
    ]

    return FlowerDetailOut(
        id=flower.id,
        name=flower.common_name_en,
        scientific=flower.scientific_name,
        family=flower.family,
        category=flower.category,
        symbol=flower.symbol,
        description=flower.description,
        photo_asset=f"assets/plants/{flower.id}.jpg",
        sections=sections_dict,
        section_details=section_details,
        sources=sources_list,
        verified_districts=verified_districts,
    )
