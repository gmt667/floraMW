"""Catalogue matching for botanical identification candidates.

Matches provider-returned scientific names against the FloraMW plant catalogue
using normalised binomial comparison. This is intentionally conservative:

- Matching requires the full normalised scientific name to match exactly.
- Synonyms, subspecies suffixes, and author abbreviations are NOT resolved;
  those require a taxonomic reference database outside this phase.
- A failed match is not an error; the candidate is preserved as an external
  (unmatched) result without creating a fake catalogue entry.

No new plants are inserted into the catalogue here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identification.provider import normalise_scientific_name
from app.models.plant import Plant

logger = logging.getLogger("floramw.identification.catalogue")


@dataclass(frozen=True)
class CatalogueMatch:
    """Result of attempting to match a scientific name against the catalogue.

    Attributes:
        matched:         True if an exact normalised match was found.
        plant_id:        FloraMW plant slug if matched, else None.
        catalogue_name:  Canonical common name from catalogue if matched.
        catalogue_scientific: Exact scientific name from catalogue if matched.
    """

    matched: bool
    plant_id: str | None = None
    catalogue_name: str | None = None
    catalogue_scientific: str | None = None


async def match_scientific_name(
    scientific_name: str,
    db: AsyncSession,
) -> CatalogueMatch:
    """Attempt to match a scientific name against the FloraMW plant catalogue.

    Uses case-insensitive and whitespace-normalised comparison via SQLAlchemy
    lower() so the match works consistently on both SQLite and PostgreSQL.

    Args:
        scientific_name: Scientific name as returned by the provider.
        db:              Active async database session.

    Returns:
        CatalogueMatch with matched=True and plant details if found,
        or matched=False if no entry corresponds to this species.
    """
    normalised = normalise_scientific_name(scientific_name)
    if not normalised:
        return CatalogueMatch(matched=False)

    stmt = select(Plant).where(
        func.lower(func.trim(Plant.scientific_name)) == normalised,
        Plant.is_published.is_(True),
    )
    result = await db.execute(stmt)
    plant = result.scalar_one_or_none()

    if plant is None:
        logger.debug(
            "No catalogue match for scientific name '%s' (normalised: '%s')",
            scientific_name,
            normalised,
        )
        return CatalogueMatch(matched=False)

    logger.debug(
        "Catalogue match: '%s' → plant_id='%s'",
        scientific_name,
        plant.id,
    )
    return CatalogueMatch(
        matched=True,
        plant_id=plant.id,
        catalogue_name=plant.common_name_en,
        catalogue_scientific=plant.scientific_name,
    )
