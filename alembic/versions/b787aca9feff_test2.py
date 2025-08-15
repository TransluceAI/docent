"""test

Revision ID: b787aca9feff
Revises: c787aca9feff
Create Date: 2025-08-15 22:59:15.924325

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b787aca9feff"
down_revision: Union[str, Sequence[str], None] = "c787aca9feff"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "transcripts", sa.Column("transcript_group_id_3", sa.String(length=36), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    return
