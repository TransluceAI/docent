"""add tmp_investigator_authorized_users table

Revision ID: d0e1d7a78abc
Revises: 198c1cd4584f
Create Date: 2025-09-23 19:04:20.849878

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0e1d7a78abc"
down_revision: Union[str, Sequence[str], None] = "198c1cd4584f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "tmp_investigator_authorized_users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_tmp_investigator_authorized_users__user_id__users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tmp_investigator_authorized_users")),
        sa.UniqueConstraint("user_id", name=op.f("uq_tmp_investigator_authorized_users__user_id")),
    )
    op.create_index(
        op.f("ix_tmp_investigator_authorized_users__user_id"),
        "tmp_investigator_authorized_users",
        ["user_id"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("tmp_investigator_authorized_users")
