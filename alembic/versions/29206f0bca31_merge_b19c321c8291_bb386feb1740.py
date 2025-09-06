"""merge b19c321c8291  bb386feb1740

Revision ID: 29206f0bca31
Revises: b19c321c8291, bb386feb1740
Create Date: 2025-09-05 00:43:21.783836

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "29206f0bca31"
down_revision: Union[str, Sequence[str], None] = ("b19c321c8291", "bb386feb1740")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
