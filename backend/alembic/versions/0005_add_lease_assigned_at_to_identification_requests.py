"""Add lease_assigned_at to identification_requests for timestamp integrity.

Revision ID: 0005_add_lease_assigned_at_to_identification_requests
Revises: 0004_add_lease_fencing_and_candidate_rank_constraint
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005_add_lease_assigned_at_to_identification_requests"
down_revision: Union[str, None] = "0004_add_lease_fencing_and_candidate_rank_constraint"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        # Step 1: Add nullable DateTime column
        with op.batch_alter_table("identification_requests") as batch_op:
            batch_op.add_column(
                sa.Column("lease_assigned_at", sa.DateTime(timezone=True), nullable=True)
            )

        # Step 2: Backfill existing records using their created_at
        op.execute(
            "UPDATE identification_requests "
            "SET lease_assigned_at = created_at "
            "WHERE lease_assigned_at IS NULL"
        )

        # Step 3: Verify no records contain NULL
        res = bind.execute(
            sa.text("SELECT COUNT(*) FROM identification_requests WHERE lease_assigned_at IS NULL")
        ).scalar()
        if res and res > 0:
            raise RuntimeError(
                f"Migration verification failed: {res} rows have NULL lease_assigned_at after backfill"
            )

        # Step 4 & 5: Alter column to nullable=False and create index
        with op.batch_alter_table("identification_requests") as batch_op:
            batch_op.alter_column(
                "lease_assigned_at",
                nullable=False,
                type_=sa.DateTime(timezone=True),
            )
            batch_op.create_index(
                "ix_identification_requests_lease_assigned_at",
                ["lease_assigned_at"],
                unique=False,
            )
    else:
        # PostgreSQL
        # Step 1: Add nullable column
        op.add_column(
            "identification_requests",
            sa.Column("lease_assigned_at", sa.DateTime(timezone=True), nullable=True),
        )

        # Step 2: Backfill existing records
        op.execute(
            "UPDATE identification_requests "
            "SET lease_assigned_at = created_at "
            "WHERE lease_assigned_at IS NULL"
        )

        # Step 3: Verify no records contain NULL
        res = bind.execute(
            sa.text("SELECT COUNT(*) FROM identification_requests WHERE lease_assigned_at IS NULL")
        ).scalar()
        if res and res > 0:
            raise RuntimeError(
                f"Migration verification failed: {res} rows have NULL lease_assigned_at after backfill"
            )

        # Step 4: Alter column to nullable=False
        op.alter_column(
            "identification_requests",
            "lease_assigned_at",
            nullable=False,
            type_=sa.DateTime(timezone=True),
        )

        # Step 5: Create index
        op.create_index(
            "ix_identification_requests_lease_assigned_at",
            "identification_requests",
            ["lease_assigned_at"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("identification_requests") as batch_op:
            batch_op.drop_index("ix_identification_requests_lease_assigned_at")
            batch_op.drop_column("lease_assigned_at")
    else:
        op.drop_index(
            "ix_identification_requests_lease_assigned_at",
            table_name="identification_requests",
        )
        op.drop_column("identification_requests", "lease_assigned_at")

