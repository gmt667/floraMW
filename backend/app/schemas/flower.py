"""Canonical Flower Pydantic schemas.

All field names support both canonical Flower terminology and the frontend lib/models.dart contract:
- FlowerSource: title, url (matches Dart: PlantSource(this.title, this.url))
- Flower list: id, name, scientific, family, category, symbol, description
- sections: Map<String, String> (matches Dart: Map<String, String>)
- Field aliases ensure full dual-compatibility (id, flower_id, plant_id).
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class FlowerSourceOut(BaseModel):
    """Matches frontend PlantSource(this.title, this.url) from lib/models.dart."""

    title: str
    url: str
    is_pmra_reference: bool = False

    model_config = ConfigDict(from_attributes=True)


class FlowerSectionOut(BaseModel):
    """Detailed botanical section with provenance metadata."""

    section_key: str
    content: str
    verification_status: str
    content_disclaimer_type: str
    source_citation: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class FlowerSummaryOut(BaseModel):
    """Flower list item — matches frontend Plant model top-level fields."""

    id: str = Field(description="Unique botanical slug identifier (e.g. 'hibiscus')")
    name: str = Field(description="Common English vernacular name")
    scientific: str = Field(description="Botanical binominal scientific name")
    family: str = Field(description="Taxonomic plant/flower family")
    category: str = Field(description="Broad category (e.g. 'Garden flowers', 'Research interest')")
    symbol: Optional[str] = Field(None, description="Visual emoji or icon symbol")
    description: str = Field(description="Short botanical overview description")
    photo_asset: str = Field(description="Relative Flutter asset path for photography")

    # Compatibility aliases for mobile integrations
    @property
    def flower_id(self) -> str:
        return self.id

    @property
    def plant_id(self) -> str:
        return self.id

    model_config = ConfigDict(from_attributes=True)


class FlowerDetailOut(FlowerSummaryOut):
    """Full botanical profile — extends summary with sections and sources."""

    sections: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value mapping matching frontend Map<String, String>",
    )
    section_details: List[FlowerSectionOut] = Field(
        default_factory=list,
        description="Sections with provenance metadata for review use",
    )
    sources: List[FlowerSourceOut] = Field(
        default_factory=list,
        description="Bibliographic sources — title/url matching frontend PlantSource",
    )
    verified_districts: List[str] = Field(
        default_factory=list,
        description="Districts in Malawi with verified occurrence",
    )


class FlowerListResponse(BaseModel):
    """Paginated flower catalog response."""

    total: int = Field(description="Total number of flowers matching query filters")
    page: int = Field(description="Current 1-based page number")
    limit: int = Field(description="Maximum number of items per page")
    total_pages: int = Field(description="Total number of available pages")
    has_more: bool = Field(description="True if additional pages are available")
    items: List[FlowerSummaryOut] = Field(description="List of flower summary items for current page")


# Backward compatibility aliases
PlantSourceOut = FlowerSourceOut
PlantSectionOut = FlowerSectionOut
PlantSummaryOut = FlowerSummaryOut
PlantDetailOut = FlowerDetailOut
PlantListResponse = FlowerListResponse
