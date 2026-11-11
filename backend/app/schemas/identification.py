"""Pydantic schemas for the identification API.

These schemas define the stable API contract between the backend and clients.
Field names are chosen to be self-documenting and Flutter-integration-friendly.

Design principles:
- All fields are explicitly typed and documented.
- Confidence is numeric, bounded, and finite; never presented as scientifically validated.
- Safety disclaimer is non-optional and always present in success responses.
- Internal state (filesystem paths, provider secrets, stack traces) is never
  included in these schemas.
- The schema supports multiple candidates so the frontend can display options.
- Error responses use a separate IdentificationErrorResponse with an appropriate
  HTTP status code rather than wrapping all failures in HTTP 200.
"""

from __future__ import annotations

import math
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ConfidenceLevel(str, Enum):
    """Human-readable confidence band derived from the numeric confidence score.

    Thresholds are configuration-driven (see Settings). These labels must
    never be presented as scientifically validated accuracy measurements.
    """

    HIGH = "high"
    MODERATE = "moderate"
    LOW = "low"
    UNCERTAIN = "uncertain"


class IdentificationOutcome(str, Enum):
    """Overall outcome of a successful identification request (HTTP 200).

    Values:
        CANDIDATES: One or more species candidates returned.
        NO_MATCH:   Provider processed the image but found no candidates.
        DEMO_MODE:  Deterministic provider returned illustrative candidates.
    """

    CANDIDATES = "candidates"
    NO_MATCH = "no_match"
    DEMO_MODE = "demo_mode"


class IdentificationErrorCode(str, Enum):
    """Stable machine-readable error codes for non-200 identification responses.

    Clients should switch on error_code to display appropriate UI states,
    not on HTTP status alone.

    Values:
        IMAGE_EMPTY:          Zero-byte upload. HTTP 400.
        IMAGE_DECODING_FAILED: Corrupted or unreadable file. HTTP 400.
        IMAGE_TOO_LARGE:      Exceeds configured size limit. HTTP 413.
        IMAGE_FORMAT_UNSUPPORTED: Not JPEG/PNG/WebP. HTTP 415.
        IMAGE_DIMENSIONS_EXCEEDED: Pixel dimensions too large. HTTP 422.
        PROVIDER_UNAVAILABLE: Provider not reachable or disabled. HTTP 503.
        PROVIDER_TIMEOUT:     Provider timed out. HTTP 504.
        PROVIDER_ERROR:       Provider returned invalid response. HTTP 502.
        IDENTIFICATION_DISABLED: No provider configured for this environment. HTTP 503.
    """

    IMAGE_EMPTY = "image_empty"
    IMAGE_DECODING_FAILED = "image_decoding_failed"
    IMAGE_TOO_LARGE = "image_too_large"
    IMAGE_FORMAT_UNSUPPORTED = "image_format_unsupported"
    IMAGE_DIMENSIONS_EXCEEDED = "image_dimensions_exceeded"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_ERROR = "provider_error"
    IDENTIFICATION_DISABLED = "identification_disabled"


# ---------------------------------------------------------------------------
# Error response schema (returned as HTTPException detail for 4xx/5xx)
# ---------------------------------------------------------------------------

_SAFETY_DISCLAIMER = (
    "Plant identification from photographs is not a substitute for expert "
    "botanical assessment. Confidence scores reflect the provider's internal "
    "model and have not been independently validated for real-world accuracy. "
    "Never determine whether a plant is safe to eat, touch, or use medicinally "
    "based solely on a visual match from this system. Toxicity, drug interactions, "
    "allergies, and risks for children, pregnancy, and breastfeeding require "
    "qualified review. If you are uncertain about a plant, consult a qualified "
    "botanist or medical professional."
)


class IdentificationErrorResponse(BaseModel):
    """Structured body for 4xx and 5xx identification responses.

    Returned as the HTTPException detail body. The Flutter client should
    parse this from the response body on non-200 responses.

    Fields:
        error_code:    Stable machine-readable error code. Never changes.
        message:       Human-readable description safe to display to users.
        retryable:     True when retrying the same request may succeed.
        safety_disclaimer: Always present — must be shown alongside error UI.
    """

    error_code: IdentificationErrorCode
    message: str
    retryable: bool
    safety_disclaimer: str = Field(default=_SAFETY_DISCLAIMER)


# ---------------------------------------------------------------------------
# Candidate schema
# ---------------------------------------------------------------------------


class IdentificationCandidateOut(BaseModel):
    """A single species candidate in an identification response.

    Catalogue match information is populated only when this species exists
    in the FloraMW plant database. External species (not in the catalogue)
    are preserved as candidates with catalogue_plant_id=None.
    """

    scientific_name: str = Field(
        description="Scientific binomial as reported by the provider."
    )
    common_names: List[str] = Field(
        default_factory=list,
        description="Common names as reported by the provider. May be empty.",
    )
    confidence: float = Field(
        description=(
            "Provider-reported confidence score, 0.0–1.0. "
            "This reflects the provider's internal scoring and has not been "
            "independently calibrated against real-world identification accuracy."
        ),
        ge=0.0,
        le=1.0,
    )
    confidence_level: ConfidenceLevel = Field(
        description="Human-readable confidence band (high/moderate/low/uncertain)."
    )
    family: Optional[str] = Field(
        default=None,
        description="Botanical family, if reported by the provider.",
    )
    genus: Optional[str] = Field(
        default=None,
        description="Genus, if reported by the provider.",
    )
    catalogue_matched: bool = Field(
        description=(
            "True if this species was found in the FloraMW plant catalogue. "
            "When False, this is an external species not currently in the catalogue."
        )
    )
    catalogue_plant_id: Optional[str] = Field(
        default=None,
        description=(
            "FloraMW plant slug for catalogue-matched species. "
            "Use this to fetch full botanical details via GET /api/v1/plants/{id}."
        ),
    )
    provider_notes: Optional[str] = Field(
        default=None,
        description="Identification notes from the provider, if any.",
    )

    @field_validator("confidence")
    @classmethod
    def confidence_must_be_finite(cls, v: float) -> float:
        """Reject NaN and infinity — they cannot be a meaningful confidence score."""
        if not math.isfinite(v):
            raise ValueError(
                f"confidence must be a finite number between 0 and 1, got {v!r}"
            )
        return v


# ---------------------------------------------------------------------------
# Provider metadata
# ---------------------------------------------------------------------------


class ProviderMetaOut(BaseModel):
    """Identification provider and model metadata.

    Included in every response so clients can display the data source and
    understand the nature of the identification (real AI vs. demo mode).
    """

    provider_id: str = Field(
        description="Stable identifier for the identification provider used."
    )
    model_version: Optional[str] = Field(
        default=None,
        description="Provider model or dataset version string.",
    )
    is_demo: bool = Field(
        description=(
            "True when the deterministic test provider was used. "
            "Demo results do not reflect image analysis and must be "
            "clearly communicated to users."
        )
    )


# ---------------------------------------------------------------------------
# Photo guidance
# ---------------------------------------------------------------------------


class PhotoGuidance(BaseModel):
    """Suggestions to improve identification quality on retry.

    Populated when confidence is low, the result is uncertain, or no match
    was found. Guides the user toward a more informative photograph.
    """

    suggested_actions: List[str] = Field(
        default_factory=list,
        description="Actionable suggestions for retaking the photograph.",
    )
    reason: str = Field(
        description="Brief explanation of why guidance is being provided.",
    )


# ---------------------------------------------------------------------------
# Main identification response (HTTP 200 only)
# ---------------------------------------------------------------------------


class IdentificationResponse(BaseModel):
    """Complete response from the plant identification endpoint (HTTP 200).

    Returned when the image is valid and the provider has processed the request,
    regardless of whether candidates were found. Non-200 HTTP responses use
    IdentificationErrorResponse instead.

    This is the stable contract consumed by the Flutter client. All fields
    are present in every response; optional fields are null when not applicable.
    """

    outcome: IdentificationOutcome = Field(
        description="Overall result of this identification request."
    )
    candidates: List[IdentificationCandidateOut] = Field(
        default_factory=list,
        description=(
            "Ordered list of species candidates (highest confidence first). "
            "Empty when outcome is NO_MATCH."
        ),
    )
    top_confidence_level: Optional[ConfidenceLevel] = Field(
        default=None,
        description=(
            "Confidence band of the highest-confidence candidate. "
            "Null when no candidates are returned."
        ),
    )
    photo_guidance: Optional[PhotoGuidance] = Field(
        default=None,
        description=(
            "Photography suggestions when confidence is low or no match found. "
            "Null when candidates have high or moderate confidence."
        ),
    )
    provider: ProviderMetaOut = Field(
        description="Provider and model metadata."
    )
    safety_disclaimer: str = Field(
        default=_SAFETY_DISCLAIMER,
        description=(
            "Safety statement that must be displayed to the user alongside "
            "any identification result. Never suppress this field."
        ),
    )
    client_request_id: Optional[str] = Field(
        default=None,
        description="Echoed client-generated request tracking identifier if provided.",
    )
    created_at: datetime = Field(
        description="UTC timestamp of when this identification was processed."
    )
