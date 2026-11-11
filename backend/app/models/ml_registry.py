"""Machine learning model and dataset metadata registry models.

Tracks model versions, deployment targets, dataset versions, and provenance
without storing large model artifacts or raw image datasets in the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.core.database import Base
from app.models.user import GUID


class ModelVersion(Base):
    """Metadata registry for machine learning models."""

    __tablename__ = "model_versions"
    __table_args__ = (
        UniqueConstraint(
            "model_id",
            "version_tag",
            name="uq_model_version_tag",
        ),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    model_id = Column(
        String(100),
        nullable=False,
        index=True,
        doc="Stable model identifier e.g. 'floramw-mobilenet'.",
    )
    version_tag = Column(
        String(50),
        nullable=False,
        index=True,
        doc="Semantic version or release tag e.g. '1.0.0'.",
    )
    provider_type = Column(
        String(50),
        nullable=False,
        default="internal",
        doc="Deployment type e.g. 'internal', 'hosted_service', 'external'.",
    )
    framework = Column(
        String(50),
        nullable=True,
        doc="Model framework/format e.g. 'onnx', 'torchscript', 'tflite'.",
    )
    artifact_uri = Column(
        String(500),
        nullable=True,
        doc="Storage URI or filesystem path to model artifact.",
    )
    associated_dataset_version = Column(
        String(50),
        nullable=True,
        doc="Version tag of dataset used for training.",
    )
    target_species_count = Column(
        Integer,
        nullable=True,
        doc="Number of botanical classes/species recognized.",
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether this model version is active for inference.",
    )
    notes = Column(
        Text,
        nullable=True,
        doc="Training, architecture, or evaluation notes.",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )


class DatasetVersion(Base):
    """Metadata registry for botanical training and validation datasets."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id",
            "version_tag",
            name="uq_dataset_version_tag",
        ),
    )

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    dataset_id = Column(
        String(100),
        nullable=False,
        index=True,
        doc="Stable dataset identifier e.g. 'floramw-malawi-flowers'.",
    )
    version_tag = Column(
        String(50),
        nullable=False,
        index=True,
        doc="Dataset release version tag e.g. '2026.1'.",
    )
    description = Column(
        Text,
        nullable=True,
        doc="Description of dataset scope, collection geography, and contents.",
    )
    species_count = Column(
        Integer,
        nullable=False,
        default=0,
        doc="Count of distinct botanical species included.",
    )
    image_count = Column(
        Integer,
        nullable=False,
        default=0,
        doc="Total number of images in the dataset.",
    )
    checksum_sha256 = Column(
        String(64),
        nullable=True,
        doc="SHA-256 archive checksum for data integrity verification.",
    )
    storage_uri = Column(
        String(500),
        nullable=True,
        doc="Storage URI or directory path for dataset archive.",
    )
    provenance = Column(
        Text,
        nullable=True,
        doc="Data origin, collectors, herbaria, or licensing info.",
    )
    validation_status = Column(
        String(50),
        nullable=False,
        default="draft",
        doc="Validation status: 'draft', 'validated', 'archived'.",
    )
    is_active = Column(
        Boolean,
        nullable=False,
        default=False,
        doc="Whether this dataset version is actively referenced.",
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
