"""Align schema with current SQLAlchemy ORM models.

Transitions from the original hand-written schema (0001_initial_schema)
to the schema defined by the current ORM models in app/models/.

Changes applied:
  users:
    - ADD password_hash (nullable)
    - ADD role VARCHAR(30) DEFAULT 'guest'
    - ADD is_anonymous BOOLEAN DEFAULT true
    - Rename full_name → (dropped), is_active → (dropped)
    - Fix email: NOT NULL → nullable
    * Implemented via table rebuild (SQLite cannot drop columns portably)

  plants:
    - RENAME common_name → common_name_en
    - ADD is_published BOOLEAN DEFAULT true
    - Drop index ix_plants_common_name, create ix_plants_common_name_en
    - Add index ix_plants_family (ORM has index=True on family)

  plant_sections:
    - ADD content_disclaimer_type VARCHAR(50) DEFAULT 'educational_summary'
    - ADD verification_status VARCHAR(50) DEFAULT 'unreviewed'
    - ADD source_citation TEXT nullable
    - ADD verified_by CHAR(36) nullable
    - ADD verified_at DATETIME nullable
    - ADD updated_at DATETIME DEFAULT CURRENT_TIMESTAMP

  plant_sources:
    - RENAME label → title
    - ADD is_pmra_reference BOOLEAN DEFAULT false
    - DROP order_index
    * Rename + drop implemented via table rebuild

  plant_distributions:
    - RENAME status → native_status
    - ADD herbarium_specimen_id VARCHAR(100) nullable
    - ADD is_verified BOOLEAN DEFAULT false
    - ADD verified_at DATETIME nullable
    * Rename implemented via table rebuild

Revision ID: 0002_align_schema_with_models
Revises:    0001_initial_schema
Create Date: 2026-11-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002_align_schema_with_models"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helper: execute raw SQL (works with both sync and async Alembic setups)
# ---------------------------------------------------------------------------
def _exec(sql: str) -> None:
    op.execute(sa.text(sql))


# ---------------------------------------------------------------------------
# UPGRADE
# ---------------------------------------------------------------------------

def upgrade() -> None:
    # ===================================================================
    # 1. USERS  — full table rebuild
    #    Old cols: id, email (NOT NULL), full_name, is_active, created_at, updated_at
    #    New cols: id, email (nullable), password_hash, role, is_anonymous, created_at, updated_at
    # ===================================================================
    _exec("ALTER TABLE users RENAME TO users_old")
    op.drop_index("ix_users_email", table_name="users_old")

    op.create_table(
        "users",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("email", sa.String(255), nullable=True, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("role", sa.String(30), nullable=False, server_default=sa.text("'guest'")),
        sa.Column(
            "is_anonymous",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
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
    # Migrate data — preserve id, email, timestamps; discard full_name/is_active
    _exec(
        "INSERT INTO users (id, email, created_at, updated_at) "
        "SELECT id, email, created_at, updated_at FROM users_old"
    )
    _exec("DROP TABLE users_old")

    # ===================================================================
    # 2. PLANTS  — rename column + add column + fix indexes
    # ===================================================================
    # SQLite 3.25+ supports RENAME COLUMN
    _exec("ALTER TABLE plants RENAME COLUMN common_name TO common_name_en")
    # Add is_published (new, NOT NULL with default; existing rows get true)
    op.add_column(
        "plants",
        sa.Column(
            "is_published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    # Update indexes
    op.drop_index("ix_plants_common_name", table_name="plants")
    op.create_index("ix_plants_common_name_en", "plants", ["common_name_en"])
    op.create_index("ix_plants_family", "plants", ["family"])

    # ===================================================================
    # 3. PLANT SECTIONS — add missing audit columns
    # ===================================================================
    op.add_column(
        "plant_sections",
        sa.Column(
            "content_disclaimer_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'educational_summary'"),
        ),
    )
    op.add_column(
        "plant_sections",
        sa.Column(
            "verification_status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'unreviewed'"),
        ),
    )
    op.add_column(
        "plant_sections",
        sa.Column("source_citation", sa.Text(), nullable=True),
    )
    op.add_column(
        "plant_sections",
        sa.Column("verified_by", sa.CHAR(36), nullable=True),
    )
    op.add_column(
        "plant_sections",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "plant_sections",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            # SQLite ADD COLUMN only accepts constant (non-function) defaults.
            # Use a fixed timestamp for existing rows; new rows get set by the ORM.
            server_default=sa.text("'1970-01-01 00:00:00'"),
        ),
    )
    # Rename the unique-constraint name to match the ORM's declared name
    # (SQLite stores constraint names inside CREATE TABLE SQL; a rebuild is the
    # only way to rename them, but since only the name differs — not the
    # semantics — we leave the existing constraint in place. The ORM uses
    # name="uq_plant_section_key" but the original table has
    # "uq_plant_sections_plant_id_section_key". Both enforce the same
    # uniqueness so functionality is identical; rename skipped to avoid an
    # unnecessary rebuild.)

    # ===================================================================
    # 4. PLANT SOURCES — rename label→title, add is_pmra_reference, drop order_index
    #    Table rebuild required (SQLite cannot drop columns in older builds,
    #    and we need to rename + drop simultaneously).
    # ===================================================================
    _exec("ALTER TABLE plant_sources RENAME TO plant_sources_old")
    op.drop_index("ix_plant_sources_plant_id", table_name="plant_sources_old")

    op.create_table(
        "plant_sources",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "plant_id",
            sa.String(64),
            sa.ForeignKey("plants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column(
            "is_pmra_reference",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index("ix_plant_sources_plant_id", "plant_sources", ["plant_id"])
    # Migrate data: label → title; url stays (may be NULL in old data — coalesce to '')
    _exec(
        "INSERT INTO plant_sources (id, plant_id, title, url) "
        "SELECT id, plant_id, label, COALESCE(url, '') FROM plant_sources_old"
    )
    _exec("DROP TABLE plant_sources_old")

    # ===================================================================
    # 5. PLANT DISTRIBUTIONS — rename status→native_status, add extra columns
    #    Table rebuild required for rename.
    # ===================================================================
    _exec("ALTER TABLE plant_distributions RENAME TO plant_distributions_old")
    op.drop_index("ix_plant_distributions_plant_id", table_name="plant_distributions_old")
    op.drop_index("ix_plant_distributions_district_id", table_name="plant_distributions_old")

    op.create_table(
        "plant_distributions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
        sa.Column(
            "plant_id",
            sa.String(64),
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
            "native_status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'introduced'"),
        ),
        sa.Column("herbarium_specimen_id", sa.String(100), nullable=True),
        sa.Column(
            "is_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "plant_id", "district_id", name="uq_plant_district_distribution"
        ),
    )
    op.create_index("ix_plant_distributions_plant_id", "plant_distributions", ["plant_id"])
    op.create_index(
        "ix_plant_distributions_district_id", "plant_distributions", ["district_id"]
    )
    # Migrate data: map 'present' status to 'introduced' (closest native_status equivalent)
    _exec(
        "INSERT INTO plant_distributions (id, plant_id, district_id, native_status) "
        "SELECT id, plant_id, district_id, "
        "CASE WHEN status = 'present' THEN 'introduced' ELSE status END "
        "FROM plant_distributions_old"
    )
    _exec("DROP TABLE plant_distributions_old")


# ---------------------------------------------------------------------------
# DOWNGRADE
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # ===================================================================
    # 5. Revert plant_distributions
    # ===================================================================
    _exec("ALTER TABLE plant_distributions RENAME TO plant_distributions_new")
    op.drop_index("ix_plant_distributions_plant_id", table_name="plant_distributions_new")
    op.drop_index("ix_plant_distributions_district_id", table_name="plant_distributions_new")

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
    op.create_index(
        "ix_plant_distributions_district_id", "plant_distributions", ["district_id"]
    )
    _exec(
        "INSERT INTO plant_distributions (id, plant_id, district_id, status) "
        "SELECT id, plant_id, district_id, 'present' FROM plant_distributions_new"
    )
    _exec("DROP TABLE plant_distributions_new")

    # ===================================================================
    # 4. Revert plant_sources
    # ===================================================================
    _exec("ALTER TABLE plant_sources RENAME TO plant_sources_new")
    op.drop_index("ix_plant_sources_plant_id", table_name="plant_sources_new")

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
    _exec(
        "INSERT INTO plant_sources (id, plant_id, label, url) "
        "SELECT id, plant_id, title, url FROM plant_sources_new"
    )
    _exec("DROP TABLE plant_sources_new")

    # ===================================================================
    # 3. Revert plant_sections — drop added audit columns
    # ===================================================================
    op.drop_column("plant_sections", "updated_at")
    op.drop_column("plant_sections", "verified_at")
    op.drop_column("plant_sections", "verified_by")
    op.drop_column("plant_sections", "source_citation")
    op.drop_column("plant_sections", "verification_status")
    op.drop_column("plant_sections", "content_disclaimer_type")

    # ===================================================================
    # 2. Revert plants
    # ===================================================================
    op.drop_index("ix_plants_family", table_name="plants")
    op.drop_index("ix_plants_common_name_en", table_name="plants")
    op.drop_column("plants", "is_published")
    _exec("ALTER TABLE plants RENAME COLUMN common_name_en TO common_name")
    op.create_index("ix_plants_common_name", "plants", ["common_name"])

    # ===================================================================
    # 1. Revert users
    # ===================================================================
    _exec("ALTER TABLE users RENAME TO users_new")
    op.drop_index("ix_users_email", table_name="users_new")

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
    _exec(
        "INSERT INTO users (id, email, created_at, updated_at) "
        "SELECT id, email, created_at, updated_at FROM users_new"
    )
    _exec("DROP TABLE users_new")
