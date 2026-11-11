"""Identification persistence models for FloraMW.

Stores identification requests and their associated candidate predictions
with full provenance, idempotency key tracking, image hashes, provider metadata,
and botanical catalogue cross-references.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.core.database import Base
from app.models.user import GUID


class IdentificationRequest(Base):
    """Represents a single plant identification request event.

    Ensures idempotency via `client_request_id` and records full execution
    provenance without storing raw image bytes in the relational database.
    """

    __tablename__ = "identification_requests"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_request_id = Column(
        String(128),
        unique=True,
        nullable=False,
        index=True,
        doc="Client-provided idempotency key or server-generated request UUID.",
    )
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Optional authenticated user ID. Null for anonymous requests.",
    )
    status = Column(
        String(30),
        nullable=False,
        default="completed",
        index=True,
        doc="Processing status: 'processing', 'completed', 'failed'.",
    )
    lease_version = Column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        index=True,
        doc="Monotonically increasing fencing token incremented on each reservation or reclamation.",
    )
    image_sha256 = Column(
        String(64),
        nullable=False,
        index=True,
        doc="Hex-encoded SHA-256 hash of sanitised image bytes for payload integrity.",
    )
    image_format = Column(
        String(10),
        nullable=False,
        doc="Canonical image format ('JPEG' or 'PNG').",
    )
    image_size_bytes = Column(
        Integer,
        nullable=False,
        doc="Byte size of the sanitised image payload.",
    )
    image_width_px = Column(
        Integer,
        nullable=True,
        doc="Image width in pixels.",
    )
    image_height_px = Column(
        Integer,
        nullable=True,
        doc="Image height in pixels.",
    )
    provider_id = Column(
        String(100),
        nullable=False,
        index=True,
        doc="Identifier of the provider that processed the image.",
    )
    model_id = Column(
        String(100),
        nullable=True,
        index=True,
        doc="Identifier of the specific model, if reported.",
    )
    model_version = Column(
        String(50),
        nullable=True,
        index=True,
        doc="Version string of the provider model or dataset.",
    )
    outcome = Column(
        String(30),
        nullable=False,
        index=True,
        doc="Overall outcome: 'candidates', 'no_match', 'demo_mode'.",
    )
    top_confidence_level = Column(
        String(20),
        nullable=True,
        doc="Confidence band of top candidate: 'high', 'moderate', 'low', 'uncertain'.",
    )
    execution_duration_ms = Column(
        Integer,
        nullable=True,
        doc="Total identification processing duration in milliseconds.",
    )
    error_code = Column(
        String(50),
        nullable=True,
        doc="Error code if identification failed.",
    )
    error_message = Column(
        Text,
        nullable=True,
        doc="Sanitised error message if identification failed.",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    completed_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    candidates = relationship(
        "IdentificationCandidate",
        back_populates="request",
        cascade="all, delete-orphan",
        order_by="IdentificationCandidate.rank",
    )


class IdentificationCandidate(Base):
    """Represents a single species candidate returned for an identification request."""

    __tablename__ = "identification_candidates"
    __table_args__ = (
        UniqueConstraint(
            "request_id",
            "rank",
            name="uq_identification_candidates_request_rank",
        ),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    request_id = Column(
        GUID(),
        ForeignKey("identification_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rank = Column(
        Integer,
        nullable=False,
        doc="Candidate rank (1 for highest confidence).",
    )
    scientific_name = Column(
        String(200),
        nullable=False,
        index=True,
        doc="Botanical species binomial.",
    )
    common_names = Column(
        Text,
        nullable=True,
        doc="JSON-encoded list of common names.",
    )
    family = Column(
        String(100),
        nullable=True,
        doc="Botanical family if reported.",
    )
    genus = Column(
        String(100),
        nullable=True,
        doc="Botanical genus if reported.",
    )
    confidence = Column(
        Float,
        nullable=False,
        doc="Provider-reported confidence score, 0.0 to 1.0.",
    )
    matched_plant_id = Column(
        String(64),
        ForeignKey("plants.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        doc="Foreign key to local botanical catalogue Plant.id if matched.",
    )
    provider_taxon_id = Column(
        String(100),
        nullable=True,
        doc="Provider's internal taxon identifier.",
    )
    notes = Column(
        Text,
        nullable=True,
        doc="Optional identification notes.",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    request = relationship("IdentificationRequest", back_populates="candidates")
    matched_plant = relationship("Plant")

    @property
    def common_names_list(self) -> List[str]:
        """Return parsed common names list from JSON."""
        if not self.common_names:
            return []
        try:
            parsed = json.loads(self.common_names)
            return parsed if isinstance(parsed, list) else []
        except (json.JSONDecodeError, TypeError):
            return []

    @common_names_list.setter
    def common_names_list(self, names: List[str]) -> None:
        """Store list of common names as JSON."""
        self.common_names = json.dumps(names or [])
