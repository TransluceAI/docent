"""add updated_at to label sets

Revision ID: e725780b6e70
Revises: a7b8c9d0e1f2
Create Date: 2026-01-27 12:58:31.969941

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e725780b6e70"
down_revision: Union[str, Sequence[str], None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add column as nullable first
    op.add_column("label_sets", sa.Column("updated_at", sa.DateTime(), nullable=True))

    # Backfill updated_at from created_at for existing rows
    op.execute("UPDATE label_sets SET updated_at = created_at WHERE updated_at IS NULL")

    # Make column non-nullable
    op.alter_column("label_sets", "updated_at", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("label_sets", "updated_at")
