"""Identification history endpoints and query service.

GET /api/v1/identifications        — paginated identification history
GET /api/v1/identifications/{id}   — full identification detail

Security Notice (Phase 3.1 Hardening):
  Public access to both history endpoints is temporarily disabled (HTTP 503)
  pending the introduction of authenticated ownership filtering in Phase 4.
  All records and candidates remain securely persisted in the database.
  No identification records, candidate details, or user identifiers are disclosed
  to unauthenticated callers.

  The underlying query and pagination logic has been optimized to eliminate N+1
  queries via correlated subqueries, ready for immediate re-activation once
  Phase 4 authentication dependencies are attached.
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

from app.core.database import get_db
from app.identification.service import confidence_level
from app.models.identification import IdentificationCandidate, IdentificationRequest
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

_AUTH_PENDING_MESSAGE = (
    "Identification history is temporarily unavailable pending "
    "user authentication integration in Phase 4. "
    "Records are securely preserved and cannot be accessed anonymously."
)


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
# Public HTTP Endpoints (Fail-Closed pending Phase 4 authentication)
# ---------------------------------------------------------------------------


@router.get(
    "",
    summary="List identification history (Temporarily Disabled)",
    description=(
        "Identification history listing is temporarily disabled pending user "
        "authentication integration in Phase 4. Returns HTTP 503. "
        "No historical identification records are exposed to unauthenticated callers."
    ),
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Identification history is temporarily unavailable pending authentication."
        }
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
    db: AsyncSession = Depends(get_db),
) -> None:
    """Fail-closed: block unauthenticated access to history listing."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_AUTH_PENDING_MESSAGE,
    )


@router.get(
    "/{identification_id}",
    summary="Get identification detail (Temporarily Disabled)",
    description=(
        "Identification detail retrieval is temporarily disabled pending user "
        "authentication integration in Phase 4. Returns HTTP 503. "
        "No historical identification records are exposed to unauthenticated callers."
    ),
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Identification detail is temporarily unavailable pending authentication."
        }
    },
)
async def get_identification(
    identification_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Fail-closed: block unauthenticated access to record detail."""
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=_AUTH_PENDING_MESSAGE,
    )
