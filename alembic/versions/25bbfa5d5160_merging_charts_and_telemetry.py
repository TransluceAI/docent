"""merging charts and telemetry

Revision ID: 25bbfa5d5160
Revises: 5c4000016f18, b6994ceb6a98
Create Date: 2025-07-31 15:55:19.244159

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "25bbfa5d5160"
down_revision: Union[str, Sequence[str], None] = ("5c4000016f18", "b6994ceb6a98")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""


def downgrade() -> None:
    """Downgrade schema."""
