"""Privacy and Personal Data lifecycle router.

Implements Section 4.D requirements:
- DELETE /api/v1/privacy/personal-data
- DELETE /api/v1/users/me/data (alias)
- DELETE /api/v1/auth/me/data (alias)

Permits an authenticated device/account to permanently purge its server-side
observations, reports, and identification records without affecting shared catalogue
data or unrelated users' records.
"""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.core.database import get_db
from app.models.flower import FlowerObservation, FlowerReport
from app.models.identification import IdentificationRequest
from app.models.user import User
from app.schemas.privacy import PersonalDataPurgeResponse

logger = logging.getLogger("floramw.api.privacy")

router = APIRouter(tags=["Privacy & Data Lifecycle"])


@router.delete(
    "/privacy/personal-data",
    response_model=PersonalDataPurgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Purge all personal data for the authenticated device/user",
    description=(
        "Permanently removes all observations, submitted reports, and "
        "identification requests associated with the authenticated account. "
        "Revokes the active device token to ensure no further access."
    ),
)
@router.delete(
    "/users/me/data",
    response_model=PersonalDataPurgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Purge all personal data for the authenticated user (Alias)",
)
@router.delete(
    "/auth/me/data",
    response_model=PersonalDataPurgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Purge all personal data for the authenticated account (Alias)",
)
async def purge_personal_data(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PersonalDataPurgeResponse:
    """Execute permanent purge of personal observations, reports, and identity."""
    user_id = user.id

    # 1. Delete observations owned by user
    stmt_obs = select(FlowerObservation).where(FlowerObservation.user_id == user_id)
    obs_list = (await db.execute(stmt_obs)).scalars().all()
    obs_count = len(obs_list)
    for obs in obs_list:
        await db.delete(obs)

    # 2. Delete reports submitted by user
    stmt_rep = select(FlowerReport).where(FlowerReport.user_id == user_id)
    rep_list = (await db.execute(stmt_rep)).scalars().all()
    rep_count = len(rep_list)
    for rep in rep_list:
        await db.delete(rep)

    # 3. Delete identification requests owned by user
    stmt_id = select(IdentificationRequest).where(IdentificationRequest.user_id == user_id)
    id_list = (await db.execute(stmt_id)).scalars().all()
    id_count = len(id_list)
    for id_req in id_list:
        await db.delete(id_req)

    # 4. Remove user account record to permanently revoke device token
    await db.delete(user)

    await db.commit()

    now_iso = datetime.now(timezone.utc).isoformat()
    logger.info(
        "Purged personal data for user %s: %d observations, %d reports, %d identification requests",
        user_id,
        obs_count,
        rep_count,
        id_count,
    )

    return PersonalDataPurgeResponse(
        status="purged",
        user_id=str(user_id),
        deleted_observations_count=obs_count,
        deleted_reports_count=rep_count,
        deleted_identification_requests_count=id_count,
        purged_at=now_iso,
        message=(
            f"Successfully purged {obs_count} observations, {rep_count} reports, "
            f"and {id_count} identification records. Device token revoked."
        ),
    )
