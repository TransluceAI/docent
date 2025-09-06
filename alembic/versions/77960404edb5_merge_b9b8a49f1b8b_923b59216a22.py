"""merge  b9b8a49f1b8b  923b59216a22

Revision ID: 77960404edb5
Revises: 923b59216a22, b9b8a49f1b8b
Create Date: 2025-09-05 18:33:16.172610

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "77960404edb5"
down_revision: Union[str, Sequence[str], None] = ("923b59216a22", "b9b8a49f1b8b")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
