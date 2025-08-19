"""merge heads 312d3aece250 and c96af745aa55

Revision ID: 1ef294fe9b86
Revises: 312d3aece250, c96af745aa55
Create Date: 2025-08-18 23:22:51.519231

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "1ef294fe9b86"
down_revision: Union[str, Sequence[str], None] = ("312d3aece250", "c96af745aa55")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
