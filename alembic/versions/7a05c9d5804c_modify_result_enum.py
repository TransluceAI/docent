"""modify result enum

Revision ID: 7a05c9d5804c
Revises: 9b87d6874efc
Create Date: 2025-12-09 14:33:13.077032

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a05c9d5804c"
down_revision: Union[str, Sequence[str], None] = "9b87d6874efc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add FAILURE to the existing resulttype enum."""

    op.execute("ALTER TYPE resulttype ADD VALUE IF NOT EXISTS 'FAILURE'")


def downgrade() -> None:
    """Downgrade schema."""
    # Enum value removals are not supported without recreating the type; no-op.
