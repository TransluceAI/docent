"""merge heads

Revision ID: ba664d6bf692
Revises: a4c8e2f13b71, c4f1e2a3b5d6
Create Date: 2026-02-11 22:13:35.575242

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "ba664d6bf692"
down_revision: Union[str, Sequence[str], None] = ("a4c8e2f13b71", "c4f1e2a3b5d6")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
