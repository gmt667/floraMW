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

    id: str
    name: str
    scientific: str
    family: str
    category: str
    symbol: Optional[str] = None
    description: str
    photo_asset: str

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

    total: int
    page: int
    limit: int
    total_pages: int
    has_more: bool
    items: List[PlantSummaryOut]
