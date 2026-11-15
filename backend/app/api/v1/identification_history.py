"""Identification history endpoints and query service.

GET /api/v1/identifications        — paginated identification history (authenticated)
GET /api/v1/identifications/{id}   — full identification detail (authenticated)

Both endpoints require a valid ``Authorization: Bearer <token>`` header issued by
``POST /api/v1/auth/anonymous``.  Unauthenticated callers receive HTTP 401.

Security:
- Each caller sees only their own records; cross-user access returns HTTP 404
  (anti-IDOR — the existence of another user's record is never disclosed).
- Pagination uses a correlated scalar subquery to count candidates, eliminating
  N+1 query overhead on both SQLite and PostgreSQL.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Optional
import uuid as _uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import get_current_user
from app.core.database import get_db
from app.identification.service import confidence_level
from app.models.identification import IdentificationCandidate, IdentificationRequest
from app.models.user import User
from app.schemas.history import (
    IdentificationCandidateHistoryOut,
    IdentificationHistoryDetailOut,
    IdentificationHistoryItemOut,
    IdentificationHistoryListResponse,
)
from app.schemas.identification import (
    ConfidenceLevel,
    IdentificationOutcome,
    ProviderMetaOut,
)

logger = logging.getLogger("floramw.api.identification_history")

router = APIRouter(prefix="/identifications", tags=["Identification History"])

# ---------------------------------------------------------------------------
# Internal Query Service Functions (Optimized with single query, no N+1)
# ---------------------------------------------------------------------------


async def fetch_identification_history_list(
    db: AsyncSession,
    *,
    outcome: Optional[str] = None,
    provider_id: Optional[str] = None,
    model_version: Optional[str] = None,
    created_after: Optional[str] = None,
    created_before: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    user_id: Optional[str] = None,
) -> IdentificationHistoryListResponse:
    """Fetch paginated identification history using an optimized single query.

    Uses a correlated scalar subquery to count candidates in the same query,
    completely eliminating N+1 query overhead across both SQLite and PostgreSQL.
    """
    # Correlated scalar subquery for candidate counts (avoids N+1 query loop)
    cand_count_subq = (
        select(func.count(IdentificationCandidate.id))
        .where(IdentificationCandidate.request_id == IdentificationRequest.id)
        .correlate(IdentificationRequest)
        .scalar_subquery()
    )

    stmt = select(IdentificationRequest, cand_count_subq.label("candidate_count")).where(
        IdentificationRequest.status == "completed"
    )

    if user_id:
        stmt = stmt.where(IdentificationRequest.user_id == user_id)

    if outcome:
        try:
            IdentificationOutcome(outcome)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid outcome value '{outcome}'. Must be 'candidates', 'no_match', or 'demo_mode'.",
            )
        stmt = stmt.where(IdentificationRequest.outcome == outcome)

    if provider_id:
        stmt = stmt.where(IdentificationRequest.provider_id == provider_id)

    if model_version:
        stmt = stmt.where(IdentificationRequest.model_version == model_version)

    if created_after:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(created_after.replace("Z", "+00:00"))
            stmt = stmt.where(IdentificationRequest.created_at >= dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid created_after datetime format: '{created_after}'.",
            )

    if created_before:
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(created_before.replace("Z", "+00:00"))
            stmt = stmt.where(IdentificationRequest.created_at <= dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid created_before datetime format: '{created_before}'.",
            )

    # Count total requests before pagination
    count_stmt = select(func.count()).select_from(
        stmt.with_only_columns(IdentificationRequest.id).subquery()
    )
    total = (await db.execute(count_stmt)).scalar_one()

    # Apply stable ordering and pagination
    stmt = stmt.order_by(IdentificationRequest.created_at.desc())
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)

    rows = (await db.execute(stmt)).all()

    total_pages = math.ceil(total / limit) if total > 0 else 1
    has_more = (page * limit) < total

    items = [
        IdentificationHistoryItemOut(
            id=str(req.id),
            client_request_id=req.client_request_id,
            outcome=IdentificationOutcome(req.outcome),
            top_confidence_level=(
                ConfidenceLevel(req.top_confidence_level)
                if req.top_confidence_level
                else None
            ),
            provider_id=req.provider_id,
            model_version=req.model_version,
            image_format=req.image_format,
            image_size_bytes=req.image_size_bytes,
            candidate_count=cand_count or 0,
            created_at=req.created_at,
        )
        for req, cand_count in rows
    ]

    return IdentificationHistoryListResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_more=has_more,
        items=items,
    )


async def fetch_identification_detail(
    identification_id: str,
    db: AsyncSession,
    *,
    user_id: Optional[str] = None,
) -> IdentificationHistoryDetailOut:
    """Fetch complete detail of an identification request with candidates."""
    try:
        req_uuid = _uuid.UUID(identification_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identification record not found.",
        )

    stmt = (
        select(IdentificationRequest)
        .options(selectinload(IdentificationRequest.candidates))
        .where(
            IdentificationRequest.id == req_uuid,
            IdentificationRequest.status == "completed",
        )
    )
    if user_id:
        stmt = stmt.where(IdentificationRequest.user_id == user_id)

    result = await db.execute(stmt)
    req = result.scalar_one_or_none()

    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identification record not found.",
        )

    candidates_out: list[IdentificationCandidateHistoryOut] = []
    for cand in sorted(req.candidates, key=lambda c: c.rank):
        try:
            common_names = json.loads(cand.common_names) if cand.common_names else []
        except (json.JSONDecodeError, TypeError):
            common_names = []

        level = confidence_level(cand.confidence)
        candidates_out.append(
            IdentificationCandidateHistoryOut(
                rank=cand.rank,
                scientific_name=cand.scientific_name,
                common_names=common_names,
                confidence=cand.confidence,
                confidence_level=level,
                family=cand.family,
                genus=cand.genus,
                catalogue_matched=cand.matched_plant_id is not None,
                catalogue_plant_id=cand.matched_plant_id,
                provider_taxon_id=cand.provider_taxon_id,
                notes=cand.notes,
            )
        )

    is_demo = req.provider_id.startswith("floramw-deterministic")

    return IdentificationHistoryDetailOut(
        id=str(req.id),
        client_request_id=req.client_request_id,
        outcome=IdentificationOutcome(req.outcome),
        top_confidence_level=(
            ConfidenceLevel(req.top_confidence_level)
            if req.top_confidence_level
            else None
        ),
        provider=ProviderMetaOut(
            provider_id=req.provider_id,
            model_version=req.model_version,
            is_demo=is_demo,
        ),
        image_format=req.image_format,
        image_size_bytes=req.image_size_bytes,
        image_width_px=req.image_width_px,
        image_height_px=req.image_height_px,
        execution_duration_ms=req.execution_duration_ms,
        candidates=candidates_out,
        created_at=req.created_at,
        completed_at=req.completed_at,
    )


# ---------------------------------------------------------------------------
# Public HTTP Endpoints (Protected by User Authentication)
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=IdentificationHistoryListResponse,
    summary="List identification history",
    description=(
        "Retrieve paginated identification history owned exclusively by the authenticated user. "
        "Requires standard 'Authorization: Bearer <token>' header. "
        "Records belonging to other users or legacy unowned records are strictly filtered out."
    ),
    responses={
        status.HTTP_200_OK: {
            "model": IdentificationHistoryListResponse,
            "description": "Paginated identification history for the authenticated caller.",
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Authentication required. Provide a valid Bearer token.",
        },
    },
)
async def list_identifications(
    outcome: Optional[str] = Query(None),
    provider_id: Optional[str] = Query(None),
    model_version: Optional[str] = Query(None),
    created_after: Optional[str] = Query(None),
    created_before: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IdentificationHistoryListResponse:
    """Retrieve user-scoped paginated identification history."""
    return await fetch_identification_history_list(
        db=db,
        outcome=outcome,
        provider_id=provider_id,
        model_version=model_version,
        created_after=created_after,
        created_before=created_before,
        page=page,
        limit=limit,
        user_id=str(current_user.id),
    )


@router.get(
    "/{identification_id}",
    response_model=IdentificationHistoryDetailOut,
    summary="Get identification detail",
    description=(
        "Retrieve complete detail and candidates for an identification record owned by the caller. "
        "Requires standard 'Authorization: Bearer <token>' header. "
        "Returns HTTP 404 if the record does not exist or belongs to another user (anti-IDOR protection)."
    ),
    responses={
        status.HTTP_200_OK: {
            "model": IdentificationHistoryDetailOut,
            "description": "Full identification detail with candidates.",
        },
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Authentication required.",
        },
        status.HTTP_404_NOT_FOUND: {
            "description": "Record not found or not owned by caller.",
        },
    },
)
async def get_identification(
    identification_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> IdentificationHistoryDetailOut:
    """Retrieve full identification detail conditioned on user ownership."""
    return await fetch_identification_detail(
        identification_id=identification_id,
        db=db,
        user_id=str(current_user.id),
    )
