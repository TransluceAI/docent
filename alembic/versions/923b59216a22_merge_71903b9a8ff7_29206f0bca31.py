"""merge 71903b9a8ff7 29206f0bca31

Revision ID: 923b59216a22
Revises: 71903b9a8ff7, 29206f0bca31
Create Date: 2025-09-05 17:38:41.259143

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "923b59216a22"
down_revision: Union[str, Sequence[str], None] = ("71903b9a8ff7", "29206f0bca31")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
