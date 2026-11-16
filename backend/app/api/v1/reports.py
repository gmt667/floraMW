"""Botanical feedback and correction report endpoints.

Allows submitting feedback, corrections, or botanical issues (Flutter ReportScreen):
- POST /api/v1/flowers/reports — Submit a botanical report or correction
- GET /api/v1/flowers/reports  — List submitted reports
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
from app.models.flower import Flower, FlowerReport
from app.models.user import User
from app.schemas.report import (
    FlowerReportCreate,
    FlowerReportListResponse,
    FlowerReportOut,
)

logger = logging.getLogger("floramw.api.reports")

router = APIRouter(tags=["Botanical Reports & Feedback"])


def _report_to_out(rep: FlowerReport) -> FlowerReportOut:
    iso_date = (
        rep.created_at.isoformat()
        if isinstance(rep.created_at, datetime)
        else str(rep.created_at)
    )
    return FlowerReportOut(
        id=str(rep.id),
        flower_id=rep.flower_id,
        plant_id=rep.flower_id,
        topic=rep.topic,
        details=rep.details,
        source=rep.source,
        status=rep.status,
        created_at=iso_date,
        createdAt=iso_date,
    )


async def _create_report_handler(
    payload: FlowerReportCreate,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerReportOut:
    if payload.flower_id:
        stmt = select(Flower).where(Flower.id == payload.flower_id, Flower.is_published.is_(True))
        result = await db.execute(stmt)
        flower = result.scalar_one_or_none()
        if not flower:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Flower '{payload.flower_id}' was not found in the catalogue.",
            )

    report_id = payload.id.strip() if payload.id and payload.id.strip() else str(uuid.uuid4())

    report = FlowerReport(
        id=report_id,
        flower_id=payload.flower_id,
        user_id=user.id if user else None,
        topic=payload.topic.strip(),
        details=payload.details.strip(),
        source=payload.source.strip() if payload.source else None,
        status=payload.status or "submitted",
        created_at=payload.created_at or datetime.now(timezone.utc),
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)

    logger.info("Submitted botanical report '%s' for flower '%s'", report.id, report.flower_id)
    return _report_to_out(report)


async def _list_reports_handler(
    flower_id: Optional[str],
    page: int,
    limit: int,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerReportListResponse:
    stmt = select(FlowerReport)

    if user:
        stmt = stmt.where(FlowerReport.user_id == user.id)

    if flower_id and flower_id.strip():
        stmt = stmt.where(FlowerReport.flower_id == flower_id.strip())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(FlowerReport.created_at.desc())
    stmt = stmt.offset((page - 1) * limit).limit(limit)

    results = (await db.execute(stmt)).scalars().all()
    items = [_report_to_out(rep) for rep in results]

    return FlowerReportListResponse(total=total, items=items)


# ---------------------------------------------------------------------------
# Canonical Flower Report Routes: /api/v1/flowers/reports and /api/v1/reports
# ---------------------------------------------------------------------------


@router.post(
    "/flowers/reports",
    response_model=FlowerReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a botanical correction or issue report",
)
@router.post(
    "/reports",
    response_model=FlowerReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a botanical correction or issue report (Alias)",
)
async def create_report(
    payload: FlowerReportCreate,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Submit a botanical report or issue draft to the backend."""
    return await _create_report_handler(payload, db, user)


@router.get(
    "/flowers/reports",
    response_model=FlowerReportListResponse,
    summary="List submitted botanical correction reports",
)
@router.get(
    "/reports",
    response_model=FlowerReportListResponse,
    summary="List submitted botanical correction reports (Alias)",
)
async def list_reports(
    flower_id: Optional[str] = Query(None, description="Filter by flower ID"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Retrieve submitted reports."""
    return await _list_reports_handler(flower_id, page, limit, db, user)
