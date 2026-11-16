"""Canonical flower naming convention, compatibility views, observations, and reports.

Revision ID: 0007_canonical_flower_naming_and_observations
Revises: 0006_add_device_token_hash_to_users
Create Date: 2026-11-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from app.models.user import GUID

# revision identifiers, used by Alembic.
revision: str = "0007_canonical_flower_naming_and_observations"
down_revision: Union[str, None] = "0006_add_device_token_hash_to_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # 1. Rename tables: plants -> flowers, plant_sections -> flower_sections, etc.
    op.rename_table("plants", "flowers")
    op.rename_table("plant_sections", "flower_sections")
    op.rename_table("plant_sources", "flower_sources")
    op.rename_table("plant_distributions", "flower_distributions")

    # 2. Rename columns to flower_id
    if is_sqlite:
        with op.batch_alter_table("flower_sections") as batch_op:
            batch_op.alter_column("plant_id", new_column_name="flower_id")
        with op.batch_alter_table("flower_sources") as batch_op:
            batch_op.alter_column("plant_id", new_column_name="flower_id")
        with op.batch_alter_table("flower_distributions") as batch_op:
            batch_op.alter_column("plant_id", new_column_name="flower_id")
        with op.batch_alter_table("identification_candidates") as batch_op:
            batch_op.alter_column("matched_plant_id", new_column_name="matched_flower_id")
    else:
        op.alter_column("flower_sections", "plant_id", new_column_name="flower_id")
        op.alter_column("flower_sources", "plant_id", new_column_name="flower_id")
        op.alter_column("flower_distributions", "plant_id", new_column_name="flower_id")
        op.alter_column("identification_candidates", "matched_plant_id", new_column_name="matched_flower_id")

    # 3. Create compatibility views so legacy Plant queries continue to work transparently
    op.execute(
        "CREATE VIEW plants AS SELECT id, common_name_en, scientific_name, family, category, symbol, description, created_at, updated_at, is_published FROM flowers;"
    )
    op.execute(
        "CREATE VIEW plant_sections AS SELECT id, flower_id AS plant_id, section_key, content, content_disclaimer_type, verification_status, source_citation, verified_by, verified_at, updated_at FROM flower_sections;"
    )
    op.execute(
        "CREATE VIEW plant_sources AS SELECT id, flower_id AS plant_id, title, url, is_pmra_reference FROM flower_sources;"
    )
    op.execute(
        "CREATE VIEW plant_distributions AS SELECT id, flower_id AS plant_id, district_id, native_status, herbarium_specimen_id, is_verified, verified_at FROM flower_distributions;"
    )

    # 4. Create flower_observations table (Field Journal)
    op.create_table(
        "flower_observations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("flower_id", sa.String(64), sa.ForeignKey("flowers.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("photo_path", sa.String(500), nullable=True),
        sa.Column("district", sa.String(100), nullable=True, index=True),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 5. Create flower_reports table (Feedback & Corrections)
    op.create_table(
        "flower_reports",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("flower_id", sa.String(64), sa.ForeignKey("flowers.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("user_id", GUID(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("topic", sa.String(100), nullable=False, index=True),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("source", sa.String(500), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="submitted", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # Drop new tables
    op.drop_table("flower_reports")
    op.drop_table("flower_observations")

    # Drop compatibility views
    op.execute("DROP VIEW IF EXISTS plant_distributions;")
    op.execute("DROP VIEW IF EXISTS plant_sources;")
    op.execute("DROP VIEW IF EXISTS plant_sections;")
    op.execute("DROP VIEW IF EXISTS plants;")

    # Rename columns back
    if is_sqlite:
        with op.batch_alter_table("identification_candidates") as batch_op:
            batch_op.alter_column("matched_flower_id", new_column_name="matched_plant_id")
        with op.batch_alter_table("flower_distributions") as batch_op:
            batch_op.alter_column("flower_id", new_column_name="plant_id")
        with op.batch_alter_table("flower_sources") as batch_op:
            batch_op.alter_column("flower_id", new_column_name="plant_id")
        with op.batch_alter_table("flower_sections") as batch_op:
            batch_op.alter_column("flower_id", new_column_name="plant_id")
    else:
        op.alter_column("identification_candidates", "matched_flower_id", new_column_name="matched_plant_id")
        op.alter_column("flower_distributions", "flower_id", new_column_name="plant_id")
        op.alter_column("flower_sources", "flower_id", new_column_name="plant_id")
        op.alter_column("flower_sections", "flower_id", new_column_name="plant_id")

    # Rename tables back
    op.rename_table("flower_distributions", "plant_distributions")
    op.rename_table("flower_sources", "plant_sources")
    op.rename_table("flower_sections", "plant_sections")
    op.rename_table("flowers", "plants")
