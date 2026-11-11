"""Add identification persistence and ML registry tables.

Creates:
  - identification_requests: Persists request metadata, idempotency key, image hashes,
    and provider/model execution outcomes.
  - identification_candidates: Persists ranked candidate predictions and catalogue linkages.
  - model_versions: Lightweight metadata registry for machine learning models.
  - dataset_versions: Lightweight metadata registry for training and evaluation datasets.

Revision ID: 0003_add_identification_persistence_and_ml_registry
Revises:    0002_align_schema_with_models
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0003_add_identification_persistence_and_ml_registry"
down_revision: Union[str, None] = "0002_align_schema_with_models"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------
    # 1. IDENTIFICATION_REQUESTS
    # -------------------------------------------------------------------
    op.create_table(
        "identification_requests",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("client_request_id", sa.String(128), nullable=False, unique=True),
        sa.Column(
            "user_id",
            sa.CHAR(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'completed'"),
        ),
        sa.Column("image_sha256", sa.String(64), nullable=False),
        sa.Column("image_format", sa.String(10), nullable=False),
        sa.Column("image_size_bytes", sa.Integer(), nullable=False),
        sa.Column("image_width_px", sa.Integer(), nullable=True),
        sa.Column("image_height_px", sa.Integer(), nullable=True),
        sa.Column("provider_id", sa.String(100), nullable=False),
        sa.Column("model_id", sa.String(100), nullable=True),
        sa.Column("model_version", sa.String(50), nullable=True),
        sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("top_confidence_level", sa.String(20), nullable=True),
        sa.Column("execution_duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_identification_requests_client_request_id",
        "identification_requests",
        ["client_request_id"],
        unique=True,
    )
    op.create_index(
        "ix_identification_requests_user_id",
        "identification_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_identification_requests_status",
        "identification_requests",
        ["status"],
    )
    op.create_index(
        "ix_identification_requests_image_sha256",
        "identification_requests",
        ["image_sha256"],
    )
    op.create_index(
        "ix_identification_requests_provider_id",
        "identification_requests",
        ["provider_id"],
    )
    op.create_index(
        "ix_identification_requests_model_id",
        "identification_requests",
        ["model_id"],
    )
    op.create_index(
        "ix_identification_requests_model_version",
        "identification_requests",
        ["model_version"],
    )
    op.create_index(
        "ix_identification_requests_outcome",
        "identification_requests",
        ["outcome"],
    )
    op.create_index(
        "ix_identification_requests_created_at",
        "identification_requests",
        ["created_at"],
    )

    # -------------------------------------------------------------------
    # 2. IDENTIFICATION_CANDIDATES
    # -------------------------------------------------------------------
    op.create_table(
        "identification_candidates",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column(
            "request_id",
            sa.CHAR(36),
            sa.ForeignKey("identification_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("scientific_name", sa.String(200), nullable=False),
        sa.Column("common_names", sa.Text(), nullable=True),
        sa.Column("family", sa.String(100), nullable=True),
        sa.Column("genus", sa.String(100), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "matched_plant_id",
            sa.String(64),
            sa.ForeignKey("plants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("provider_taxon_id", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "request_id",
            "rank",
            name="uq_identification_request_rank",
        ),
    )
    op.create_index(
        "ix_identification_candidates_request_id",
        "identification_candidates",
        ["request_id"],
    )
    op.create_index(
        "ix_identification_candidates_scientific_name",
        "identification_candidates",
        ["scientific_name"],
    )
    op.create_index(
        "ix_identification_candidates_matched_plant_id",
        "identification_candidates",
        ["matched_plant_id"],
    )

    # -------------------------------------------------------------------
    # 3. MODEL_VERSIONS
    # -------------------------------------------------------------------
    op.create_table(
        "model_versions",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("model_id", sa.String(100), nullable=False),
        sa.Column("version_tag", sa.String(50), nullable=False),
        sa.Column(
            "provider_type",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'internal'"),
        ),
        sa.Column("framework", sa.String(50), nullable=True),
        sa.Column("artifact_uri", sa.String(500), nullable=True),
        sa.Column("associated_dataset_version", sa.String(50), nullable=True),
        sa.Column("target_species_count", sa.Integer(), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "model_id",
            "version_tag",
            name="uq_model_version_tag",
        ),
    )
    op.create_index(
        "ix_model_versions_model_id",
        "model_versions",
        ["model_id"],
    )
    op.create_index(
        "ix_model_versions_version_tag",
        "model_versions",
        ["version_tag"],
    )

    # -------------------------------------------------------------------
    # 4. DATASET_VERSIONS
    # -------------------------------------------------------------------
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("dataset_id", sa.String(100), nullable=False),
        sa.Column("version_tag", sa.String(50), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "species_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "image_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("checksum_sha256", sa.String(64), nullable=True),
        sa.Column("storage_uri", sa.String(500), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column(
            "validation_status",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "dataset_id",
            "version_tag",
            name="uq_dataset_version_tag",
        ),
    )
    op.create_index(
        "ix_dataset_versions_dataset_id",
        "dataset_versions",
        ["dataset_id"],
    )
    op.create_index(
        "ix_dataset_versions_version_tag",
        "dataset_versions",
        ["version_tag"],
    )


def downgrade() -> None:
    op.drop_table("dataset_versions")
    op.drop_table("model_versions")
    op.drop_table("identification_candidates")
    op.drop_table("identification_requests")
