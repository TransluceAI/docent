"""drop api_keys timestamp indices

Revision ID: a7b8c9d0e1f2
Revises: 5c581f3bd108
Create Date: 2026-01-28 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, Sequence[str], None] = "5c581f3bd108"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            op.f("ix_api_keys__disabled_at"),
            table_name="api_keys",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            op.f("ix_api_keys__last_used_at"),
            table_name="api_keys",
            postgresql_concurrently=True,
            if_exists=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            op.f("ix_api_keys__disabled_at"),
            "api_keys",
            ["disabled_at"],
            unique=False,
            postgresql_concurrently=True,
        )
        op.create_index(
            op.f("ix_api_keys__last_used_at"),
            "api_keys",
            ["last_used_at"],
            unique=False,
            postgresql_concurrently=True,
        )
