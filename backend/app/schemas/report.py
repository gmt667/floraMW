"""Pydantic schemas for botanical feedback and correction reports.

Corresponds to Flutter lib/screens/profile.dart ReportScreen & lib/screens/settings.dart DraftsScreen:
- plantId / flower_id: String?
- topic: String
- details: String
- source / source_reference: String?
- status: String
- createdAt / created_at: String (ISO 8601)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FlowerReportCreate(BaseModel):
    """Schema for submitting a botanical report or correction."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(None, max_length=64, description="Optional client-generated ID")
    flower_id: Optional[str] = Field(None, alias="flowerId", max_length=64, description="Botanical flower slug")
    plant_id: Optional[str] = Field(None, alias="plantId", max_length=64, description="Compatibility alias for flower_id")
    topic: str = Field(..., min_length=2, max_length=100, description="Report category or topic")
    details: str = Field(..., min_length=5, max_length=5000, description="Correction details")
    source: Optional[str] = Field(None, max_length=500, description="Reference citation or source")
    source_reference: Optional[str] = Field(None, alias="sourceReference", max_length=500, description="Alias matching backend documentation")
    status: str = Field(default="submitted", max_length=30, description="Report status ('submitted', 'in_review', etc.)")
    created_at: Optional[datetime] = Field(None, alias="createdAt", description="Report timestamp")

    @model_validator(mode="after")
    def validate_report_fields(self) -> FlowerReportCreate:
        if not self.flower_id and self.plant_id:
            self.flower_id = self.plant_id
        if not self.source and self.source_reference:
            self.source = self.source_reference
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)
        return self


class FlowerReportUpdate(BaseModel):
    """Schema for updating a botanical report or changing review status."""

    model_config = ConfigDict(populate_by_name=True)

    status: Optional[str] = Field(
        None,
        max_length=30,
        description="Updated status: 'submitted', 'in_review', 'resolved', 'rejected', 'local-draft'",
    )
    topic: Optional[str] = Field(None, min_length=2, max_length=100, description="Updated topic category")
    details: Optional[str] = Field(None, min_length=5, max_length=5000, description="Updated report details")
    source: Optional[str] = Field(None, max_length=500, description="Updated reference citation")
    source_reference: Optional[str] = Field(None, alias="sourceReference", max_length=500)

    @model_validator(mode="after")
    def validate_update_fields(self) -> FlowerReportUpdate:
        if not self.source and self.source_reference:
            self.source = self.source_reference
        return self


class FlowerReportOut(BaseModel):
    """Report response schema."""

    id: str = Field(description="Unique report ID")
    flower_id: Optional[str] = Field(None, description="Target flower slug")
    plant_id: Optional[str] = Field(None, description="Compatibility alias for flower_id")
    topic: str = Field(description="Report category")
    details: str = Field(description="Report details")
    source: Optional[str] = Field(None, description="Reference source")
    source_reference: Optional[str] = Field(None, description="Alias for source")
    status: str = Field(description="Processing status")
    created_at: str = Field(description="ISO 8601 formatted timestamp")
    createdAt: str = Field(description="CamelCase alias for Flutter compatibility")

    model_config = ConfigDict(from_attributes=True)


class FlowerReportListResponse(BaseModel):
    """List response for reports."""

    total: int = Field(description="Total reports submitted")
    items: List[FlowerReportOut] = Field(description="List of reports")


# Backward compatibility aliases
ReportCreate = FlowerReportCreate
ReportUpdate = FlowerReportUpdate
ReportOut = FlowerReportOut
ReportListResponse = FlowerReportListResponse
