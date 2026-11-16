"""Field Journal observation endpoints.

Provides endpoints for mobile field observations (Flutter Discovery):
- POST /api/v1/flowers/observations       — Record a new field observation
- GET /api/v1/flowers/observations        — List observations with pagination
- GET /api/v1/flowers/observations/{id}   — Fetch single observation details
- PATCH /api/v1/flowers/observations/{id} — Update observation notes or district
- DELETE /api/v1/flowers/observations/{id}— Remove observation
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_current_user
from app.core.database import get_db
from app.models.flower import Flower, FlowerObservation
from app.models.user import User
from app.schemas.observation import (
    FlowerObservationCreate,
    FlowerObservationListResponse,
    FlowerObservationOut,
    FlowerObservationUpdate,
)

logger = logging.getLogger("floramw.api.observations")

router = APIRouter(tags=["Field Journal Observations"])


def _observation_to_out(obs: FlowerObservation) -> FlowerObservationOut:
    iso_date = (
        obs.created_at.isoformat()
        if isinstance(obs.created_at, datetime)
        else str(obs.created_at)
    )
    return FlowerObservationOut(
        id=str(obs.id),
        flower_id=obs.flower_id,
        plant_id=obs.flower_id,
        created_at=iso_date,
        createdAt=iso_date,
        photo_path=obs.photo_path,
        photo=obs.photo_path,
        district=obs.district,
        note=obs.note or "",
        is_demo=obs.is_demo,
    )


async def _create_observation_handler(
    payload: FlowerObservationCreate,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerObservationOut:
    # Verify target flower exists in catalogue
    stmt = select(Flower).where(Flower.id == payload.flower_id, Flower.is_published.is_(True))
    result = await db.execute(stmt)
    flower = result.scalar_one_or_none()
    if not flower:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Flower '{payload.flower_id}' was not found in the botanical catalogue.",
        )

    obs_id = payload.id.strip() if payload.id and payload.id.strip() else str(uuid.uuid4())

    # Check if observation with this ID already exists
    existing_stmt = select(FlowerObservation).where(FlowerObservation.id == obs_id)
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Observation with ID '{obs_id}' already exists.",
        )

    obs = FlowerObservation(
        id=obs_id,
        flower_id=payload.flower_id,
        user_id=user.id if user else None,
        created_at=payload.created_at or datetime.now(timezone.utc),
        photo_path=payload.photo_path,
        district=payload.district,
        note=payload.note or "",
        is_demo=payload.is_demo,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(obs)
    await db.commit()
    await db.refresh(obs)

    logger.info("Recorded observation '%s' for flower '%s'", obs.id, obs.flower_id)
    return _observation_to_out(obs)


async def _list_observations_handler(
    flower_id: Optional[str],
    district: Optional[str],
    is_demo: Optional[bool],
    page: int,
    limit: int,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerObservationListResponse:
    stmt = select(FlowerObservation)

    # If authenticated, filter by user ownership
    if user:
        stmt = stmt.where(FlowerObservation.user_id == user.id)

    if flower_id and flower_id.strip():
        stmt = stmt.where(FlowerObservation.flower_id == flower_id.strip())

    if district and district.strip():
        stmt = stmt.where(func.lower(FlowerObservation.district) == district.strip().lower())

    if is_demo is not None:
        stmt = stmt.where(FlowerObservation.is_demo.is_(is_demo))

    # Count
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Order and paginate
    stmt = stmt.order_by(FlowerObservation.created_at.desc())
    stmt = stmt.offset((page - 1) * limit).limit(limit)

    results = (await db.execute(stmt)).scalars().all()
    items = [_observation_to_out(obs) for obs in results]

    return FlowerObservationListResponse(total=total, items=items)


async def _get_observation_handler(
    obs_id: str,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerObservationOut:
    stmt = select(FlowerObservation).where(FlowerObservation.id == obs_id.strip())
    obs = (await db.execute(stmt)).scalar_one_or_none()
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{obs_id}' was not found.",
        )

    # Anti-IDOR: if created by another user, hide existence
    if user and obs.user_id and obs.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{obs_id}' was not found.",
        )

    return _observation_to_out(obs)


async def _update_observation_handler(
    obs_id: str,
    payload: FlowerObservationUpdate,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerObservationOut:
    stmt = select(FlowerObservation).where(FlowerObservation.id == obs_id.strip())
    obs = (await db.execute(stmt)).scalar_one_or_none()
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{obs_id}' was not found.",
        )

    if user and obs.user_id and obs.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{obs_id}' was not found.",
        )

    if payload.note is not None:
        obs.note = payload.note
    if payload.district is not None:
        obs.district = payload.district

    obs.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(obs)

    return _observation_to_out(obs)


async def _delete_observation_handler(
    obs_id: str,
    db: AsyncSession,
    user: Optional[User],
) -> None:
    stmt = select(FlowerObservation).where(FlowerObservation.id == obs_id.strip())
    obs = (await db.execute(stmt)).scalar_one_or_none()
    if not obs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{obs_id}' was not found.",
        )

    if user and obs.user_id and obs.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Observation '{obs_id}' was not found.",
        )

    await db.delete(obs)
    await db.commit()


# ---------------------------------------------------------------------------
# Canonical Flower Observation Routes: /api/v1/flowers/observations
# ---------------------------------------------------------------------------


@router.post(
    "/flowers/observations",
    response_model=FlowerObservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new field journal observation",
)
@router.post(
    "/observations",
    response_model=FlowerObservationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new field journal observation (Alias)",
)
async def create_observation(
    payload: FlowerObservationCreate,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Record an observation in the Field Journal with flower reference and notes."""
    return await _create_observation_handler(payload, db, user)


@router.get(
    "/flowers/observations",
    response_model=FlowerObservationListResponse,
    summary="List recorded field journal observations",
)
@router.get(
    "/observations",
    response_model=FlowerObservationListResponse,
    summary="List recorded field journal observations (Alias)",
)
async def list_observations(
    flower_id: Optional[str] = Query(None, description="Filter by flower ID"),
    district: Optional[str] = Query(None, description="Filter by district"),
    is_demo: Optional[bool] = Query(None, description="Filter by demo status"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Retrieve observations recorded by this user/device."""
    return await _list_observations_handler(flower_id, district, is_demo, page, limit, db, user)


@router.get(
    "/flowers/observations/{obs_id}",
    response_model=FlowerObservationOut,
    summary="Get single field journal observation",
)
@router.get(
    "/observations/{obs_id}",
    response_model=FlowerObservationOut,
    summary="Get single field journal observation (Alias)",
)
async def get_observation(
    obs_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Retrieve a specific field observation by identifier."""
    return await _get_observation_handler(obs_id, db, user)


@router.patch(
    "/flowers/observations/{obs_id}",
    response_model=FlowerObservationOut,
    summary="Update field journal observation notes or district",
)
@router.patch(
    "/observations/{obs_id}",
    response_model=FlowerObservationOut,
    summary="Update field journal observation notes or district (Alias)",
)
async def update_observation(
    obs_id: str,
    payload: FlowerObservationUpdate,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Update field notes or district for a saved observation."""
    return await _update_observation_handler(obs_id, payload, db, user)


@router.delete(
    "/flowers/observations/{obs_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a field journal observation",
)
@router.delete(
    "/observations/{obs_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a field journal observation (Alias)",
)
async def delete_observation(
    obs_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Delete a field observation from the journal."""
    await _delete_observation_handler(obs_id, db, user)
