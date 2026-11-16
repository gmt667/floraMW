"""Legacy Plant models compatibility module.

FloraMW now uses Flower as its canonical terminology.
This module re-exports Flower classes as Plant aliases to preserve backward compatibility.
"""

from app.models.flower import (
    Flower as Plant,
    FlowerSection as PlantSection,
    FlowerSource as PlantSource,
    FlowerDistribution as PlantDistribution,
    FlowerObservation as PlantObservation,
    FlowerReport as PlantReport,
    FlowerObservation as Discovery,
    FlowerReport as Report,
    Flower,
    FlowerSection,
    FlowerSource,
    FlowerDistribution,
    FlowerObservation,
    FlowerReport,
)

__all__ = [
    "Plant",
    "PlantSection",
    "PlantSource",
    "PlantDistribution",
    "PlantObservation",
    "PlantReport",
    "Discovery",
    "Report",
    "Flower",
    "FlowerSection",
    "FlowerSource",
    "FlowerDistribution",
    "FlowerObservation",
    "FlowerReport",
]
