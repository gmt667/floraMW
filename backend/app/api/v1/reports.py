"""Botanical feedback and correction report endpoints.

Allows submitting feedback, corrections, or botanical issues (Flutter ReportScreen):
- POST /api/v1/flowers/reports       — Submit a botanical report or correction
- GET  /api/v1/flowers/reports       — List submitted reports (user-isolated)
- GET  /api/v1/flowers/reports/{id}  — Fetch a single report (owner-isolated)
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_optional_current_user
from app.core.database import get_db
from app.models.flower import Flower, FlowerReport
from app.models.user import User
from app.schemas.report import (
    FlowerReportCreate,
    FlowerReportUpdate,
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
        source_reference=rep.source,
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

    # Check for duplicate report ID
    existing_stmt = select(FlowerReport).where(FlowerReport.id == report_id)
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report with ID '{report_id}' already exists.",
        )

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
    try:
        await db.commit()
        await db.refresh(report)
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Report with ID '{report_id}' already exists or conflicts with existing data.",
        ) from exc

    logger.info("Submitted botanical report '%s' for flower '%s'", report.id, report.flower_id)
    return _report_to_out(report)


async def _list_reports_handler(
    flower_id: Optional[str],
    status_filter: Optional[str],
    topic: Optional[str],
    all_users: bool,
    page: int,
    limit: int,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerReportListResponse:
    stmt = select(FlowerReport)

    if all_users:
        if user is None or user.role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative access required to list reports across all users.",
            )
    else:
        if user:
            stmt = stmt.where(FlowerReport.user_id == user.id)
        else:
            stmt = stmt.where(FlowerReport.user_id.is_(None))

    if flower_id and flower_id.strip():
        stmt = stmt.where(FlowerReport.flower_id == flower_id.strip())

    if status_filter and status_filter.strip():
        stmt = stmt.where(FlowerReport.status == status_filter.strip())

    if topic and topic.strip():
        stmt = stmt.where(func.lower(FlowerReport.topic) == topic.strip().lower())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(FlowerReport.created_at.desc())
    stmt = stmt.offset((page - 1) * limit).limit(limit)

    results = (await db.execute(stmt)).scalars().all()
    items = [_report_to_out(rep) for rep in results]

    return FlowerReportListResponse(total=total, items=items)


async def _get_report_handler(
    report_id: str,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerReportOut:
    stmt = select(FlowerReport).where(FlowerReport.id == report_id.strip())
    report = (await db.execute(stmt)).scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' was not found.",
        )

    is_admin = user is not None and user.role == "admin"
    is_owner = report.user_id is None if user is None else report.user_id == user.id

    # Anti-IDOR: only owner or administrator may view report
    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' was not found.",
        )

    return _report_to_out(report)


async def _update_report_handler(
    report_id: str,
    payload: FlowerReportUpdate,
    db: AsyncSession,
    user: Optional[User],
) -> FlowerReportOut:
    stmt = select(FlowerReport).where(FlowerReport.id == report_id.strip())
    report = (await db.execute(stmt)).scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' was not found.",
        )

    is_admin = user is not None and user.role == "admin"
    is_owner = report.user_id is None if user is None else report.user_id == user.id

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' was not found.",
        )

    if payload.status is not None:
        if not is_admin and payload.status != report.status:
            if payload.status not in ("submitted", "local-draft"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only administrative users can resolve or advance report status.",
                )
        report.status = payload.status

    if payload.topic is not None:
        report.topic = payload.topic.strip()
    if payload.details is not None:
        report.details = payload.details.strip()
    if payload.source is not None:
        report.source = payload.source.strip() if payload.source else None

    await db.commit()
    await db.refresh(report)
    logger.info("Updated report '%s' (status=%s)", report.id, report.status)
    return _report_to_out(report)


async def _delete_report_handler(
    report_id: str,
    db: AsyncSession,
    user: Optional[User],
) -> None:
    stmt = select(FlowerReport).where(FlowerReport.id == report_id.strip())
    report = (await db.execute(stmt)).scalar_one_or_none()
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' was not found.",
        )

    is_admin = user is not None and user.role == "admin"
    is_owner = report.user_id is None if user is None else report.user_id == user.id

    if not is_admin and not is_owner:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Report '{report_id}' was not found.",
        )

    await db.delete(report)
    await db.commit()
    logger.info("Deleted report '%s'", report_id)


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
    status: Optional[str] = Query(None, description="Filter by report status ('submitted', 'in_review', etc.)"),
    topic: Optional[str] = Query(None, description="Filter by report category"),
    all_users: bool = Query(False, description="Admin-only: list reports across all users"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Retrieve submitted reports for the authenticated caller or unowned session."""
    return await _list_reports_handler(flower_id, status, topic, all_users, page, limit, db, user)


@router.get(
    "/flowers/reports/admin",
    response_model=FlowerReportListResponse,
    summary="Administrative report management queue",
)
@router.get(
    "/reports/admin",
    response_model=FlowerReportListResponse,
    summary="Administrative report management queue (Alias)",
)
async def list_admin_reports(
    flower_id: Optional[str] = Query(None, description="Filter by flower ID"),
    status: Optional[str] = Query(None, description="Filter by report status"),
    topic: Optional[str] = Query(None, description="Filter by report topic"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Administrative review queue listing reports across all users (Requires admin role)."""
    return await _list_reports_handler(flower_id, status, topic, True, page, limit, db, user)


@router.get(
    "/flowers/reports/{report_id}",
    response_model=FlowerReportOut,
    summary="Get single botanical correction report",
)
@router.get(
    "/reports/{report_id}",
    response_model=FlowerReportOut,
    summary="Get single botanical correction report (Alias)",
)
async def get_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Retrieve details of a single report by ID."""
    return await _get_report_handler(report_id, db, user)


@router.patch(
    "/flowers/reports/{report_id}",
    response_model=FlowerReportOut,
    summary="Update report details or resolution status",
)
@router.patch(
    "/reports/{report_id}",
    response_model=FlowerReportOut,
    summary="Update report details or resolution status (Alias)",
)
async def update_report(
    report_id: str,
    payload: FlowerReportUpdate,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Update report details (owner) or advance resolution status (admin)."""
    return await _update_report_handler(report_id, payload, db, user)


@router.delete(
    "/flowers/reports/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a botanical report",
)
@router.delete(
    "/reports/{report_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a botanical report (Alias)",
)
async def delete_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(get_optional_current_user),
):
    """Delete a botanical report (owner or administrator)."""
    await _delete_report_handler(report_id, db, user)
