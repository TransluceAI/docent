"""add updated_at to filters

Revision ID: c4f1e2a3b5d6
Revises: b3f7a2c8d910
Create Date: 2026-02-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f1e2a3b5d6"
down_revision: Union[str, Sequence[str], None] = "b3f7a2c8d910"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("filters", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE filters SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("filters", "updated_at", nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("filters", "updated_at")
