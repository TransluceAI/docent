"""merge heads

Revision ID: 3e944ba3908f
Revises: 665580d96b03, a7b8c9d0e1f2
Create Date: 2026-01-28 16:51:19.089733

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "3e944ba3908f"
down_revision: Union[str, Sequence[str], None] = ("665580d96b03", "a7b8c9d0e1f2")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
