"""add metadata_json to collections

Revision ID: a4c8e2f13b71
Revises: b3f7a2c8d910
Create Date: 2026-02-11 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c8e2f13b71"
down_revision: Union[str, Sequence[str], None] = "b3f7a2c8d910"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "collections",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("collections", "metadata_json")
