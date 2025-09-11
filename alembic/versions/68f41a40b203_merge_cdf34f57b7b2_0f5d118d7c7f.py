"""merge cdf34f57b7b2 0f5d118d7c7f

Revision ID: 68f41a40b203
Revises: 0f5d118d7c7f, cdf34f57b7b2
Create Date: 2025-09-10 22:35:36.588866

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "68f41a40b203"
down_revision: Union[str, Sequence[str], None] = ("0f5d118d7c7f", "cdf34f57b7b2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
