"""Pydantic schemas for identification history API endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.identification import (
    ConfidenceLevel,
    IdentificationCandidateOut,
    IdentificationOutcome,
    ProviderMetaOut,
)


class IdentificationCandidateHistoryOut(BaseModel):
    """Candidate as returned from persisted history records."""

    rank: int
    scientific_name: str
    common_names: List[str] = Field(default_factory=list)
    confidence: float
    confidence_level: ConfidenceLevel
    family: Optional[str] = None
    genus: Optional[str] = None
    catalogue_matched: bool
    catalogue_plant_id: Optional[str] = None
    provider_taxon_id: Optional[str] = None
    notes: Optional[str] = None


class IdentificationHistoryItemOut(BaseModel):
    """Summary record of a completed identification request for list views."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Identification request UUID.")
    client_request_id: str
    outcome: IdentificationOutcome
    top_confidence_level: Optional[ConfidenceLevel] = None
    provider_id: str
    model_version: Optional[str] = None
    image_format: str
    image_size_bytes: int
    candidate_count: int = Field(default=0)
    created_at: datetime


class IdentificationHistoryDetailOut(BaseModel):
    """Full detail of a persisted identification request including all candidates."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    client_request_id: str
    outcome: IdentificationOutcome
    top_confidence_level: Optional[ConfidenceLevel] = None
    provider: ProviderMetaOut
    image_format: str
    image_size_bytes: int
    image_width_px: Optional[int] = None
    image_height_px: Optional[int] = None
    execution_duration_ms: Optional[int] = None
    candidates: List[IdentificationCandidateHistoryOut] = Field(default_factory=list)
    created_at: datetime
    completed_at: Optional[datetime] = None


class IdentificationHistoryListResponse(BaseModel):
    """Paginated list of identification history records."""

    total: int
    page: int
    limit: int
    total_pages: int
    has_more: bool
    items: List[IdentificationHistoryItemOut]
