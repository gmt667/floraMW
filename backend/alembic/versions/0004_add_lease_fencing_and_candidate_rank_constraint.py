"""Add lease fencing to identification requests and enforce candidate rank uniqueness.

Modifications:
  - identification_requests:
      - Adds lease_version (Integer, NOT NULL, default 1) for optimistic lease fencing
        and stale-worker prevention.
      - Adds index on lease_version.
  - identification_candidates:
      - Enforces canonical unique constraint/index uq_identification_candidates_request_rank
        on (request_id, rank).

Revision ID: 0004_add_lease_fencing_and_candidate_rank_constraint
Revises:    0003_add_identification_persistence_and_ml_registry
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0004_add_lease_fencing_and_candidate_rank_constraint"
down_revision: Union[str, None] = "0003_add_identification_persistence_and_ml_registry"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # -------------------------------------------------------------------
    # 1. IDENTIFICATION_REQUESTS — Add lease_version column and index
    # -------------------------------------------------------------------
    with op.batch_alter_table("identification_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "lease_version",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.create_index(
            "ix_identification_requests_lease_version",
            ["lease_version"],
            unique=False,
        )

    # -------------------------------------------------------------------
    # 2. IDENTIFICATION_CANDIDATES — Ensure canonical unique constraint
    # -------------------------------------------------------------------
    if is_sqlite:
        op.create_index(
            "uq_identification_candidates_request_rank",
            "identification_candidates",
            ["request_id", "rank"],
            unique=True,
            if_not_exists=True,
        )
    else:
        op.create_unique_constraint(
            "uq_identification_candidates_request_rank",
            "identification_candidates",
            ["request_id", "rank"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    # -------------------------------------------------------------------
    # 2. IDENTIFICATION_CANDIDATES — Drop canonical unique constraint
    # -------------------------------------------------------------------
    if is_sqlite:
        op.drop_index(
            "uq_identification_candidates_request_rank",
            table_name="identification_candidates",
            if_exists=True,
        )
    else:
        op.drop_constraint(
            "uq_identification_candidates_request_rank",
            "identification_candidates",
            type_="unique",
        )

    # -------------------------------------------------------------------
    # 1. IDENTIFICATION_REQUESTS — Remove lease_version column and index
    # -------------------------------------------------------------------
    with op.batch_alter_table("identification_requests") as batch_op:
        batch_op.drop_index("ix_identification_requests_lease_version")
        batch_op.drop_column("lease_version")
