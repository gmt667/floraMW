"""Plant Pydantic schemas (Backward-compatibility wrapper).

FloraMW canonical terminology uses Flower.
This module preserves the legacy Plant schema names.
"""

from app.schemas.flower import (
    FlowerSourceOut,
    FlowerSectionOut,
    FlowerSummaryOut,
    FlowerDetailOut,
    FlowerListResponse,
    PlantSourceOut,
    PlantSectionOut,
    PlantSummaryOut,
    PlantDetailOut,
    PlantListResponse,
)

__all__ = [
    "FlowerSourceOut",
    "FlowerSectionOut",
    "FlowerSummaryOut",
    "FlowerDetailOut",
    "FlowerListResponse",
    "PlantSourceOut",
    "PlantSectionOut",
    "PlantSummaryOut",
    "PlantDetailOut",
    "PlantListResponse",
]
