"""Deterministic test provider for FloraMW identification engine.

THIS PROVIDER IS STRICTLY FOR DEVELOPMENT AND TESTING.

It does not perform image analysis. It does not connect to any external service.
It returns a fixed, predictable set of candidates drawn from the real FloraMW
botanical catalogue. The candidates are always the same regardless of the image
content.

This provider exists so that:
- The identification engine can be fully exercised without a paid AI service.
- Tests can assert on response structure and catalogue matching.
- The Flutter client can be integrated against a stable contract.

It MUST NOT be used in production. The service layer enforces this by raising
MockProviderForbiddenError when ENVIRONMENT is 'production' and this provider
is active.

Identification results produced by this provider carry an explicit disclaimer
in the API response. No confidence scores are presented as real predictions.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.identification.exceptions import MockProviderForbiddenError
from app.identification.provider import (
    ImagePayload,
    ProviderCandidate,
    ProviderResult,
)

logger = logging.getLogger("floramw.identification.deterministic")

# ---------------------------------------------------------------------------
# Catalogue species used by this provider.
# These scientific names MUST correspond to plants in the FloraMW database.
# Source: lib/models.dart final plants = <Plant>[...]
# ---------------------------------------------------------------------------
_CATALOGUE_CANDIDATES: list[ProviderCandidate] = [
    ProviderCandidate(
        scientific_name="Hibiscus rosa-sinensis",
        common_names=["Chinese hibiscus"],
        confidence=0.72,
        family="Malvaceae",
        genus="Hibiscus",
        provider_taxon_id="deterministic:hibiscus",
        notes=(
            "Deterministic test candidate — not an image prediction. "
            "Confidence score is illustrative, not calibrated."
        ),
    ),
    ProviderCandidate(
        scientific_name="Catharanthus roseus",
        common_names=["Madagascar periwinkle"],
        confidence=0.55,
        family="Apocynaceae",
        genus="Catharanthus",
        provider_taxon_id="deterministic:periwinkle",
        notes=(
            "Deterministic test candidate — not an image prediction. "
            "Confidence score is illustrative, not calibrated."
        ),
    ),
    ProviderCandidate(
        scientific_name="Tagetes erecta",
        common_names=["African marigold"],
        confidence=0.38,
        family="Asteraceae",
        genus="Tagetes",
        provider_taxon_id="deterministic:marigold",
        notes=(
            "Deterministic test candidate — not an image prediction. "
            "Confidence score is illustrative, not calibrated."
        ),
    ),
]

PROVIDER_ID = "floramw-deterministic-v1"
_SIMULATED_DELAY_SECONDS = 0.05  # minimal delay; enough to test async paths


class DeterministicProvider:
    """Deterministic test provider.

    Returns a fixed set of real-catalogue candidates with illustrative
    confidence scores. Used exclusively for development and testing.
    """

    provider_id: str = PROVIDER_ID

    async def identify(self, image: ImagePayload) -> ProviderResult:
        """Return a fixed deterministic result regardless of image content.

        Raises:
            MockProviderForbiddenError: When called in production environment.
        """
        if settings.ENVIRONMENT == "production" or not settings.ALLOW_MOCK_PROVIDER:
            raise MockProviderForbiddenError(
                "The deterministic test provider is forbidden in production or when ALLOW_MOCK_PROVIDER is False. "
                "Configure a real identification provider before deploying."
            )

        logger.warning(
            "DeterministicProvider invoked [environment=%s, format=%s, "
            "size=%d bytes, %dx%d px]. This is NOT a real identification.",
            settings.ENVIRONMENT,
            image.format,
            image.size_bytes,
            image.width_px,
            image.height_px,
        )

        # Minimal async yield to exercise the async code path in tests
        await asyncio.sleep(_SIMULATED_DELAY_SECONDS)

        return ProviderResult(
            candidates=list(_CATALOGUE_CANDIDATES),
            provider_id=PROVIDER_ID,
            model_version="deterministic-fixed-2026-11",
            provider_meta={
                "note": "Deterministic test provider. No image analysis performed.",
                "image_format": image.format,
                "image_size_bytes": image.size_bytes,
            },
        )
