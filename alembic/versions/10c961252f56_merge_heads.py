"""merge heads

Revision ID: 10c961252f56
Revises: 22c6507954e1, 46af4e44ae1a, 665580d96b03
Create Date: 2026-01-16 22:01:17.776319

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "10c961252f56"
down_revision: Union[str, Sequence[str], None] = ("22c6507954e1", "46af4e44ae1a", "665580d96b03")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
