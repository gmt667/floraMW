"""Plant Pydantic schemas.

All field names match the frontend lib/models.dart contract exactly:
- PlantSource: title, url  (matches Dart: PlantSource(this.title, this.url))
- Plant list: id, name, scientific, family, category, symbol, description
- sections: Map<String, String>  (matches Dart: Map<String, String>)
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PlantSourceOut(BaseModel):
    """Matches frontend PlantSource(this.title, this.url) from lib/models.dart."""

    title: str
    url: str
    is_pmra_reference: bool = False

    model_config = ConfigDict(from_attributes=True)


class PlantSectionOut(BaseModel):
    """Detailed section with provenance metadata (not exposed to frontend directly)."""

    section_key: str
    content: str
    verification_status: str
    content_disclaimer_type: str
    source_citation: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class PlantSummaryOut(BaseModel):
    """Plant list item — matches frontend Plant model top-level fields."""

    id: str = Field(description="Unique botanical slug identifier (e.g. 'hibiscus')")
    name: str = Field(description="Common English vernacular name")
    scientific: str = Field(description="Botanical binominal scientific name")
    family: str = Field(description="Taxonomic plant family")
    category: str = Field(description="Broad category (e.g. 'Garden flowers', 'Research interest')")
    symbol: Optional[str] = Field(None, description="Visual emoji or icon symbol")
    description: str = Field(description="Short botanical overview description")
    photo_asset: str = Field(description="Relative Flutter asset path for photography")

    model_config = ConfigDict(from_attributes=True)


class PlantDetailOut(PlantSummaryOut):
    """Full botanical profile — extends summary with sections and sources."""

    sections: Dict[str, str] = Field(
        default_factory=dict,
        description="Key-value mapping matching frontend Map<String, String>",
    )
    section_details: List[PlantSectionOut] = Field(
        default_factory=list,
        description="Sections with provenance metadata for admin/review use",
    )
    sources: List[PlantSourceOut] = Field(
        default_factory=list,
        description="Bibliographic sources — title/url matching frontend PlantSource",
    )
    verified_districts: List[str] = Field(
        default_factory=list,
        description="Districts in Malawi with verified occurrence",
    )


class PlantListResponse(BaseModel):
    """Paginated plant catalog response."""

    total: int = Field(description="Total number of plants matching query filters")
    page: int = Field(description="Current 1-based page number")
    limit: int = Field(description="Maximum number of items per page")
    total_pages: int = Field(description="Total number of available pages")
    has_more: bool = Field(description="True if additional pages are available")
    items: List[PlantSummaryOut] = Field(description="List of plant summary items for current page")
