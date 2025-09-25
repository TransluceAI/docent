"""Add tools field to base_contexts table

Revision ID: f20f579831f7
Revises: d0e1d7a78abc
Create Date: 2025-09-24 06:18:30.030998

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f20f579831f7"
down_revision: Union[str, Sequence[str], None] = "d0e1d7a78abc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("base_contexts", sa.Column("tools", sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("base_contexts", "tools")
