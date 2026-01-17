"""add tags to dql allowed tables

Revision ID: 46af4e44ae1a
Revises: 6335bfb185cb
Create Date: 2026-01-15 19:49:02.074702

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "46af4e44ae1a"
down_revision: Union[str, Sequence[str], None] = "6335bfb185cb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DQL_ROLE = "docent_dql_reader"


def upgrade() -> None:
    """Allow the DQL role to read the tags table."""
    op.execute(f"GRANT SELECT ON tags TO {_DQL_ROLE};")


def downgrade() -> None:
    """Revoke the DQL role's ability to read the tags table."""
    op.execute(f"REVOKE SELECT ON tags FROM {_DQL_ROLE};")
