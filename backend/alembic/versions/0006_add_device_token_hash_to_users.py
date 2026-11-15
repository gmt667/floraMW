"""Add device_token_hash to users for anonymous identity authentication.

Revision ID: 0006_add_device_token_hash_to_users
Revises: 0005_add_lease_assigned_at_to_identification_requests
Create Date: 2026-11-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0006_add_device_token_hash_to_users"
down_revision: Union[str, None] = "0005_add_lease_assigned_at_to_identification_requests"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column("device_token_hash", sa.String(64), nullable=True)
            )
            batch_op.create_index(
                "ix_users_device_token_hash",
                ["device_token_hash"],
                unique=True,
            )
    else:
        op.add_column(
            "users",
            sa.Column("device_token_hash", sa.String(64), nullable=True),
        )
        op.create_index(
            "ix_users_device_token_hash",
            "users",
            ["device_token_hash"],
            unique=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_index("ix_users_device_token_hash")
            batch_op.drop_column("device_token_hash")
    else:
        op.drop_index("ix_users_device_token_hash", table_name="users")
        op.drop_column("users", "device_token_hash")

