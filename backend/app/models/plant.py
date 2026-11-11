from datetime import datetime, timezone
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
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.user import GUID


class Plant(Base):
    __tablename__ = "plants"

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
        "PlantSection",
        back_populates="plant",
        cascade="all, delete-orphan",
        order_by="PlantSection.id",
    )
    sources = relationship(
        "PlantSource",
        back_populates="plant",
        cascade="all, delete-orphan",
        order_by="PlantSource.id",
    )
    distributions = relationship(
        "PlantDistribution",
        back_populates="plant",
        cascade="all, delete-orphan",
    )


class PlantSection(Base):
    __tablename__ = "plant_sections"
    __table_args__ = (
        UniqueConstraint("plant_id", "section_key", name="uq_plant_section_key"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plant_id = Column(
        String(64),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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

    plant = relationship("Plant", back_populates="sections")


class PlantSource(Base):
    __tablename__ = "plant_sources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    plant_id = Column(
        String(64),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title = Column(String(255), nullable=False)
    url = Column(String(500), nullable=False)
    is_pmra_reference = Column(Boolean, nullable=False, default=False)

    plant = relationship("Plant", back_populates="sources")


class PlantDistribution(Base):
    __tablename__ = "plant_distributions"
    __table_args__ = (
        UniqueConstraint("plant_id", "district_id", name="uq_plant_district_distribution"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    plant_id = Column(
        String(64),
        ForeignKey("plants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
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

    plant = relationship("Plant", back_populates="distributions")
    district = relationship("District", back_populates="distributions")

