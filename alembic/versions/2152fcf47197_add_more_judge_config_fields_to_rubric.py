"""add more judge config fields to rubric

Revision ID: 2152fcf47197
Revises: c14dd8b8762d
Create Date: 2025-10-13 16:44:55.998126

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2152fcf47197"
down_revision: Union[str, Sequence[str], None] = "c14dd8b8762d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create the enum first
    judge_variant_enum = sa.Enum("MAJORITY", "MULTI_REFLECT", name="judgevariant")
    judge_variant_enum.create(op.get_bind(), checkfirst=True)

    op.add_column("rubrics", sa.Column("n_rollouts_per_input", sa.Integer(), nullable=True))
    op.add_column(
        "rubrics",
        sa.Column(
            "judge_variant",
            judge_variant_enum,
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
