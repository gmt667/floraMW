"""Identification history endpoints.

GET /api/v1/identifications        — paginated identification history
GET /api/v1/identifications/{id}   — full identification detail

Authentication note:
  User authentication endpoints are not yet implemented (Phase 4).
  History records are therefore publicly readable by ID.
  The user_id association column is fully present in the schema so that
  per-user filtering can be activated in Phase 4 by adding a Depends(get_current_user)
  dependency without any database migration.

  When authentication is added:
  - Authenticated users will see only their own records.
  - Anonymous identifications (user_id IS NULL) are accessible only by id.
  - Admin role will be granted read access to all records.

Security:
  - No image bytes are stored or returned; only metadata and candidates.
  - Identification IDs are UUIDs; they are not guessable in sequence.
  - Internal paths, stack traces, and credentials are never included in responses.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.identification.service import _confidence_level
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


# ---------------------------------------------------------------------------
# GET /api/v1/identifications
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=IdentificationHistoryListResponse,
    summary="List identification history",
    description=(
        "Retrieve a paginated list of past plant identification requests. "
        "Supports filtering by outcome, provider, model version, and date range. "
        "Note: Per-user filtering will be activated in Phase 4 when authentication is implemented."
    ),
)
async def list_identifications(
    outcome: Optional[str] = Query(None, description="Filter by outcome: 'candidates', 'no_match', or 'demo_mode'."),
    provider_id: Optional[str] = Query(None, description="Filter by provider identifier."),
    model_version: Optional[str] = Query(None, description="Filter by model version string."),
    created_after: Optional[str] = Query(None, description="ISO 8601 datetime lower bound (inclusive)."),
    created_before: Optional[str] = Query(None, description="ISO 8601 datetime upper bound (inclusive)."),
    page: int = Query(1, ge=1, description="Page number (1-based)."),
    limit: int = Query(20, ge=1, le=100, description="Records per page."),
    db: AsyncSession = Depends(get_db),
) -> IdentificationHistoryListResponse:
    """Return a paginated, filtered list of identification history records."""
    stmt = select(IdentificationRequest)

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
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(created_after.replace("Z", "+00:00"))
            stmt = stmt.where(IdentificationRequest.created_at >= dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid created_after datetime format: '{created_after}'.",
            )

    if created_before:
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(created_before.replace("Z", "+00:00"))
            stmt = stmt.where(IdentificationRequest.created_at <= dt)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid created_before datetime format: '{created_before}'.",
            )

    # Count total before pagination
    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    # Apply stable ordering and pagination
    stmt = stmt.order_by(IdentificationRequest.created_at.desc())
    offset = (page - 1) * limit
    stmt = stmt.offset(offset).limit(limit)

    rows = (await db.execute(stmt)).scalars().all()

    # Get candidate counts in one query
    total_pages = math.ceil(total / limit) if total > 0 else 1
    has_more = (page * limit) < total

    items = []
    for req in rows:
        # Count candidates for this request
        cand_count_stmt = (
            select(func.count())
            .where(IdentificationCandidate.request_id == req.id)
        )
        cand_count = (await db.execute(cand_count_stmt)).scalar_one()

        items.append(
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
                candidate_count=cand_count,
                created_at=req.created_at,
            )
        )

    return IdentificationHistoryListResponse(
        total=total,
        page=page,
        limit=limit,
        total_pages=total_pages,
        has_more=has_more,
        items=items,
    )


# ---------------------------------------------------------------------------
# GET /api/v1/identifications/{identification_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{identification_id}",
    response_model=IdentificationHistoryDetailOut,
    summary="Get identification detail",
    description=(
        "Retrieve the complete persisted record for a single identification request, "
        "including all candidates and provider metadata."
    ),
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Identification record not found."},
    },
)
async def get_identification(
    identification_id: str,
    db: AsyncSession = Depends(get_db),
) -> IdentificationHistoryDetailOut:
    """Return the full detail of a persisted identification request."""
    # Parse UUID safely
    import uuid as _uuid
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
        .where(IdentificationRequest.id == req_uuid)
    )
    result = await db.execute(stmt)
    req = result.scalar_one_or_none()

    if req is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Identification record not found.",
        )

    # Build candidate list
    candidates_out: list[IdentificationCandidateHistoryOut] = []
    for cand in sorted(req.candidates, key=lambda c: c.rank):
        try:
            common_names = json.loads(cand.common_names) if cand.common_names else []
        except (json.JSONDecodeError, TypeError):
            common_names = []

        level = _confidence_level(cand.confidence)
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
