"""Provider contract for botanical plant identification.

Defines the data structures and Protocol that any identification provider must
satisfy. The application service depends only on this contract, not on any
vendor-specific SDK or external API.

Adding a new provider means implementing IdentificationProvider and registering
it via configuration — no changes to the service or API layer are needed.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Provider input
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImagePayload:
    """Sanitised image bytes and metadata passed to a provider.

    Constructed by the image validation layer. Providers receive only validated,
    decoded data — they must not re-read from the filesystem.

    Attributes:
        content:    Raw image bytes (JPEG or PNG, decoded and re-encoded by
                    the validation step to ensure integrity and strip EXIF).
        format:     Canonical format string: 'JPEG' or 'PNG'.
        width_px:   Image width after any EXIF orientation correction.
        height_px:  Image height after any EXIF orientation correction.
        size_bytes: Byte length of content.
    """

    content: bytes
    format: str
    width_px: int
    height_px: int
    size_bytes: int


# ---------------------------------------------------------------------------
# Provider output
# ---------------------------------------------------------------------------


@dataclass
class ProviderCandidate:
    """A single species candidate returned by a provider.

    Attributes:
        scientific_name:   Species binomial as returned by the provider.
                           Not normalised; normalisation happens in the service.
        common_names:      List of common names as reported by the provider.
                           May be empty. Do not invent names.
        confidence:        Provider-reported confidence score, 0.0–1.0.
                           Reflects provider internal scoring; not independently
                           calibrated against real-world identification accuracy.
        family:            Botanical family, if reported.
        genus:             Genus, if reported.
        provider_taxon_id: Provider's internal taxon identifier, if available.
                           Useful for linking to provider documentation.
        notes:             Optional identification notes from the provider.
    """

    scientific_name: str
    confidence: float
    common_names: list[str] = field(default_factory=list)
    family: str | None = None
    genus: str | None = None
    provider_taxon_id: str | None = None
    notes: str | None = None


@dataclass
class ProviderResult:
    """Complete result returned by an identification provider.

    Attributes:
        candidates:    Ordered list of species candidates (highest confidence
                       first). May be empty when the provider finds no match.
        provider_id:   Stable identifier for this provider implementation, e.g.
                       'floramw-deterministic-v1'. Used in audit trails.
        model_version: Provider model or dataset version string, if available.
        provider_meta: Optional arbitrary key/value metadata from the provider
                       (e.g. processing time, region). Never exposed directly
                       in API responses; used only for internal diagnostics.
    """

    candidates: list[ProviderCandidate]
    provider_id: str
    model_version: str | None = None
    provider_meta: dict[str, object] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IdentificationProvider(Protocol):
    """Contract that every identification provider must satisfy.

    Providers are synchronous from the perspective of the application service
    (they block until a result is available), but may use async internally.
    The service calls `identify` and awaits the coroutine.
    """

    provider_id: str
    """Stable identifier string for this provider, used in responses and logs."""

    async def identify(self, image: ImagePayload) -> ProviderResult:
        """Submit an image and return identification candidates.

        Args:
            image: Validated image payload constructed by the ingestion layer.

        Returns:
            ProviderResult with zero or more candidates.

        Raises:
            ProviderUnavailableError: Provider cannot be reached.
            ProviderTimeoutError:     Provider did not respond in time.
            ProviderResponseError:    Provider returned an invalid response.
            MockProviderForbiddenError: Mock provider invoked in production.
        """
        ...


# ---------------------------------------------------------------------------
# Scientific name normalisation utility (used by both service and providers)
# ---------------------------------------------------------------------------


def normalise_scientific_name(name: str) -> str:
    """Return a consistently normalised scientific name for catalogue matching.

    Applies:
    - Unicode NFC normalisation
    - Whitespace collapsing
    - Lower-casing

    This is intentionally conservative. It does not attempt to handle
    synonyms, subspecies markers, or authority abbreviations — those require
    a taxonomic database. The goal is reliable equality comparison between
    provider output and catalogue entries that differ only in casing or
    whitespace.

    Example:
        'Hibiscus  rosa-sinensis ' → 'hibiscus rosa-sinensis'
    """
    if not name:
        return ""
    normalised = unicodedata.normalize("NFC", name)
    collapsed = " ".join(normalised.split())
    return collapsed.lower()


# ---------------------------------------------------------------------------
# Provider resolution factory
# ---------------------------------------------------------------------------


def get_identification_provider() -> IdentificationProvider:
    """Resolve and return the configured identification provider.

    Enforces environment safety:
    - If provider is 'deterministic', 'mock', or 'test', verifies that
      ENVIRONMENT is not 'production' and ALLOW_MOCK_PROVIDER is True.
    - If provider is unconfigured or disabled, raises ProviderUnavailableError.
    - If provider name is unknown, raises ProviderUnavailableError.

    Raises:
        MockProviderForbiddenError: If mock provider is requested in production or disallowed.
        ProviderUnavailableError: If identification is disabled or provider is not configured.
    """
    from app.core.config import settings
    from app.identification.exceptions import (
        MockProviderForbiddenError,
        ProviderUnavailableError,
    )

    provider_name = (settings.IDENTIFICATION_PROVIDER or "").strip().lower()

    if provider_name in ("deterministic", "mock", "test"):
        if settings.ENVIRONMENT == "production" or not settings.ALLOW_MOCK_PROVIDER:
            raise MockProviderForbiddenError(
                "The deterministic test provider is forbidden in production or when ALLOW_MOCK_PROVIDER is False. "
                "Configure a verified production botanical identification provider."
            )
        from app.identification.deterministic_provider import DeterministicProvider

        return DeterministicProvider()
    elif provider_name in ("plantnet", "plant_net"):
        from app.identification.plantnet_provider import PlantNetProvider

        return PlantNetProvider()
    elif provider_name in ("disabled", "none", ""):
        raise ProviderUnavailableError(
            "Botanical plant identification is currently disabled in configuration."
        )
    else:
        raise ProviderUnavailableError(
            f"Configured identification provider '{settings.IDENTIFICATION_PROVIDER}' "
            "is not available or not yet integrated."
        )
