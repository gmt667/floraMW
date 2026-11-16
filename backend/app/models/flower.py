"""Canonical Flower, Section, Source, Distribution, Observation, and Report ORM Models.

FloraMW canonical terminology uses flower/flowers for all botanical entities
while maintaining backward-compatible mappings to legacy Plant identifiers.
"""

from datetime import datetime, timezone
import uuid
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship, synonym
from app.core.database import Base
from app.models.user import GUID


class Flower(Base):
    """Canonical Flower entity representing a botanical profile in FloraMW."""

    __tablename__ = "flowers"

    id = Column(String(64), primary_key=True)  # Stable slug e.g. 'hibiscus'
    scientific_name = Column(String(150), unique=True, nullable=False, index=True)
    common_name_en = Column(String(150), nullable=False, index=True)
    family = Column(String(100), nullable=False, index=True)
    category = Column(String(50), nullable=False, index=True)
    symbol = Column(String(10), nullable=True)
    description = Column(Text, nullable=False)
    is_published = Column(Boolean, nullable=False, default=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    sections = relationship(
        "FlowerSection",
        back_populates="flower",
        cascade="all, delete-orphan",
        order_by="FlowerSection.id",
    )
    sources = relationship(
        "FlowerSource",
        back_populates="flower",
        cascade="all, delete-orphan",
        order_by="FlowerSource.id",
    )
    distributions = relationship(
        "FlowerDistribution",
        back_populates="flower",
        cascade="all, delete-orphan",
    )
    observations = relationship(
        "FlowerObservation",
        back_populates="flower",
        cascade="all, delete-orphan",
    )
    reports = relationship(
        "FlowerReport",
        back_populates="flower",
    )


class FlowerSection(Base):
    """Botanical information section associated with a flower."""

    __tablename__ = "flower_sections"
    __table_args__ = (
        UniqueConstraint("flower_id", "section_key", name="uq_flower_section_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    flower_id = Column(
        String(64),
        ForeignKey("flowers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id = synonym("flower_id")
    section_key = Column(String(100), nullable=False, index=True)
    content = Column(Text, nullable=False)
    content_disclaimer_type = Column(
        String(50), nullable=False, default="educational_summary"
    )
    verification_status = Column(
        String(50), nullable=False, default="unreviewed"
    )  # 'unreviewed', 'pending_review', 'verified', 'disputed'
    source_citation = Column(Text, nullable=True)
    verified_by = Column(GUID(), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    flower = relationship("Flower", back_populates="sections")
    plant = synonym("flower")


class FlowerSource(Base):
    """Bibliographic or institutional reference source for a flower."""

    __tablename__ = "flower_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    flower_id = Column(
        String(64),
        ForeignKey("flowers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id = synonym("flower_id")
    title = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    is_pmra_reference = Column(Boolean, nullable=False, default=False)

    flower = relationship("Flower", back_populates="sources")
    plant = synonym("flower")


class FlowerDistribution(Base):
    """Documented distribution of a flower across Malawi's 28 districts."""

    __tablename__ = "flower_distributions"
    __table_args__ = (
        UniqueConstraint("flower_id", "district_id", name="uq_flower_district_distribution"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    flower_id = Column(
        String(64),
        ForeignKey("flowers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id = synonym("flower_id")
    district_id = Column(
        Integer,
        ForeignKey("districts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    native_status = Column(String(50), nullable=False, default="introduced")
    herbarium_specimen_id = Column(String(100), nullable=True)
    is_verified = Column(Boolean, nullable=False, default=False)
    verified_at = Column(DateTime(timezone=True), nullable=True)

    flower = relationship("Flower", back_populates="distributions")
    plant = synonym("flower")
    district = relationship("District", back_populates="distributions")


class FlowerObservation(Base):
    """Field Journal observation recorded by a mobile user.

    Corresponds to Flutter Discovery in lib/models.dart:
    id, plantId/flower_id, createdAt, photo, district, note.
    """

    __tablename__ = "flower_observations"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    flower_id = Column(
        String(64),
        ForeignKey("flowers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plant_id = synonym("flower_id")
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    photo_path = Column(String(500), nullable=True)
    district = Column(String(100), nullable=True, index=True)
    note = Column(Text, nullable=False, default="")
    is_demo = Column(Boolean, nullable=False, default=False)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    flower = relationship("Flower", back_populates="observations")
    plant = synonym("flower")
    user = relationship("User")


class FlowerReport(Base):
    """User feedback, botanical correction, or issue draft report.

    Corresponds to Flutter ReportScreen & DraftsScreen in lib/screens/profile.dart:
    plantId/flower_id, topic, details, source, status, createdAt.
    """

    __tablename__ = "flower_reports"

    id = Column(String(64), primary_key=True, default=lambda: str(uuid.uuid4()))
    flower_id = Column(
        String(64),
        ForeignKey("flowers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    plant_id = synonym("flower_id")
    user_id = Column(
        GUID(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    topic = Column(String(100), nullable=False, index=True)
    details = Column(Text, nullable=False)
    source = Column(String(500), nullable=True)
    status = Column(String(30), nullable=False, default="submitted", index=True)
    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )

    flower = relationship("Flower", back_populates="reports")
    plant = synonym("flower")
    user = relationship("User")
