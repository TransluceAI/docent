"""test

Revision ID: c787aca9feff
Revises: d787aca9feff
Create Date: 2025-08-15 22:58:15.924325

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c787aca9feff"
down_revision: Union[str, Sequence[str], None] = "d787aca9feff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transcripts", sa.Column("transcript_group_id_2", sa.String(length=36), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    return
