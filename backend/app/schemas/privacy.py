"""Pydantic schemas for Privacy and Personal Data lifecycle endpoints.

Complies with Section 4.D Privacy & Personal-Data Lifecycle requirements:
- Strictly scoped to authenticated identity
- Detailed category counts (observations, reports, requests)
- Timestamped audit confirmation
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class PersonalDataPurgeResponse(BaseModel):
    """Structured response confirming personal data purge."""

    status: str = Field(default="purged", description="Purge operation status ('purged')")
    user_id: str = Field(description="ID of the authenticated user whose personal data was purged")
    deleted_observations_count: int = Field(description="Number of field journal observations permanently deleted")
    deleted_reports_count: int = Field(description="Number of botanical feedback reports permanently deleted")
    deleted_identification_requests_count: int = Field(description="Number of identification requests purged/anonymized")
    purged_at: str = Field(description="ISO 8601 formatted timestamp of the purge execution")
    message: str = Field(description="Summary confirmation message")


# Compatibility aliases
PrivacyPurgeResponse = PersonalDataPurgeResponse
