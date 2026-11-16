"""Pydantic schemas for Field Journal observations (Flutter Discovery model).

Fully compatible with Flutter lib/models.dart Discovery:
- id: String
- plantId / flower_id: String
- createdAt / created_at: String (ISO 8601)
- photo / photo_path: String?
- district: String?
- note: String
- isDemo / is_demo: bool
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator


class FlowerObservationCreate(BaseModel):
    """Schema for creating a Field Journal observation."""

    model_config = ConfigDict(populate_by_name=True)

    id: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Optional client-generated ID (e.g. timestamp/microseconds matching Flutter)",
    )
    flower_id: Optional[str] = Field(
        default=None,
        alias="flowerId",
        max_length=64,
        description="Botanical flower slug (e.g. 'hibiscus')",
    )
    plant_id: Optional[str] = Field(
        default=None,
        alias="plantId",
        max_length=64,
        description="Legacy alias for flower_id matching Flutter Discovery.plantId",
    )
    created_at: Optional[datetime] = Field(
        default=None,
        alias="createdAt",
        description="Observation timestamp (defaults to current UTC time if not provided)",
    )
    photo_path: Optional[str] = Field(
        default=None,
        alias="photoPath",
        max_length=500,
        description="Local device or remote storage photo path",
    )
    photo: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Alias for photo_path matching Flutter Discovery.photo",
    )
    district: Optional[str] = Field(
        default=None,
        max_length=100,
        description="District where observation was recorded (e.g. 'Zomba')",
    )
    note: str = Field(
        default="",
        max_length=2000,
        description="Field notes entered by user (up to 2000 chars matching Flutter JournalScreen)",
    )
    is_demo: bool = Field(
        default=False,
        alias="isDemo",
        description="True if saved from demo mode identification, False if verified/live observation",
    )

    @model_validator(mode="after")
    def validate_flower_and_photo(self) -> FlowerObservationCreate:
        # Normalize plant_id into flower_id
        if not self.flower_id and self.plant_id:
            self.flower_id = self.plant_id
        if not self.flower_id:
            raise ValueError("Either flower_id or plant_id must be provided")

        # Normalize photo into photo_path
        if not self.photo_path and self.photo:
            self.photo_path = self.photo

        # Default created_at to now
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc)

        return self


class FlowerObservationUpdate(BaseModel):
    """Schema for updating an existing observation's notes or district."""

    model_config = ConfigDict(populate_by_name=True)

    note: Optional[str] = Field(None, max_length=2000, description="Updated field notes")
    district: Optional[str] = Field(None, max_length=100, description="Updated district name")


class FlowerObservationOut(BaseModel):
    """Field Journal observation output schema matching Flutter Discovery."""

    id: str = Field(description="Unique observation ID")
    flower_id: str = Field(description="Botanical flower identifier")
    plant_id: str = Field(description="Compatibility alias matching Flutter Discovery.plantId")
    created_at: str = Field(description="ISO 8601 formatted timestamp")
    createdAt: str = Field(description="CamelCase alias matching Flutter Discovery.createdAt")
    photo_path: Optional[str] = Field(None, description="Path or URL to saved observation photo")
    photo: Optional[str] = Field(None, description="Alias matching Flutter Discovery.photo")
    district: Optional[str] = Field(None, description="District where observation was recorded")
    note: str = Field(default="", description="Field notes")
    is_demo: bool = Field(default=False, description="Whether this is a demo discovery")

    model_config = ConfigDict(from_attributes=True)


class FlowerObservationListResponse(BaseModel):
    """List response for Field Journal observations."""

    total: int = Field(description="Total observations recorded by this user/device")
    items: List[FlowerObservationOut] = Field(description="List of observations ordered newest first")


# Backward compatibility aliases
DiscoveryOut = FlowerObservationOut
DiscoveryCreate = FlowerObservationCreate
DiscoveryUpdate = FlowerObservationUpdate
