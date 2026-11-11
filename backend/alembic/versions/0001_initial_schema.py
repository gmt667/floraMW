"""Initial database schema for FloraMW — original applied schema.

This migration records the EXACT schema that was actually applied to the
first development database (floramw.db).  It is NOT the current target
schema.  Migration 0002_align_schema_with_models brings any existing
database forward to the current SQLAlchemy models without data loss.

The original schema was hand-written and differs from the current ORM in
several ways:
  - plants.common_name instead of plants.common_name_en
  - plants.symbol is NOT NULL (ORM: nullable)
  - plants lacks is_published
  - users has full_name / is_active instead of password_hash / role / is_anonymous
  - plant_sources uses 'label' + 'order_index' instead of 'title' + 'is_pmra_reference'
  - plant_sections lacks all audit columns
  - plant_distributions uses 'status' instead of 'native_status' and lacks herbarium/verified fields

Revision ID: 0001_initial_schema
Revises:    (none — this is the base)
Create Date: 2026-11-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Users — original hand-written schema
    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # 2. Districts — original schema (VARCHAR lengths wider than ORM, safe)
    op.create_table(
        "districts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("region", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_districts_name", "districts", ["name"], unique=True)
    op.create_index("ix_districts_region", "districts", ["region"])

    # 3. Plants — original schema uses 'common_name', not 'common_name_en'
    op.create_table(
        "plants",
        sa.Column("id", sa.String(100), primary_key=True, nullable=False),
        sa.Column("common_name", sa.String(255), nullable=False),
        sa.Column("scientific_name", sa.String(255), nullable=False, unique=True),
        sa.Column("family", sa.String(255), nullable=False),
        sa.Column("category", sa.String(100), nullable=False),
        sa.Column("symbol", sa.String(50), nullable=False),   # ORM later makes this nullable
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_plants_common_name", "plants", ["common_name"])
    op.create_index("ix_plants_scientific_name", "plants", ["scientific_name"], unique=True)
    op.create_index("ix_plants_category", "plants", ["category"])

    # 4. Plant sections — original schema lacks all audit columns
    op.create_table(
        "plant_sections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "plant_id",
            sa.String(100),
            sa.ForeignKey("plants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("section_key", sa.String(100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "plant_id", "section_key", name="uq_plant_sections_plant_id_section_key"
        ),
    )
    op.create_index("ix_plant_sections_plant_id", "plant_sections", ["plant_id"])

    # 5. Plant sources — original schema uses 'label' and 'order_index', not 'title'/'is_pmra_reference'
    op.create_table(
        "plant_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "plant_id",
            sa.String(100),
            sa.ForeignKey("plants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("url", sa.String(1024), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index("ix_plant_sources_plant_id", "plant_sources", ["plant_id"])

    # 6. Plant distributions — original schema uses 'status', not 'native_status'
    op.create_table(
        "plant_distributions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "plant_id",
            sa.String(100),
            sa.ForeignKey("plants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "district_id",
            sa.Integer(),
            sa.ForeignKey("districts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'present'"),
        ),
        sa.UniqueConstraint(
            "plant_id", "district_id", name="uq_plant_distributions_plant_district"
        ),
    )
    op.create_index("ix_plant_distributions_plant_id", "plant_distributions", ["plant_id"])
    op.create_index("ix_plant_distributions_district_id", "plant_distributions", ["district_id"])


def downgrade() -> None:
    op.drop_table("plant_distributions")
    op.drop_table("plant_sources")
    op.drop_table("plant_sections")
    op.drop_table("plants")
    op.drop_table("districts")
    op.drop_table("users")
