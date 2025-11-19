"""update telemetry accumulation index

Revision ID: 7575b151dce9
Revises: 77807d29d9d5
Create Date: 2025-11-18 21:22:27.536747

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7575b151dce9"
down_revision: Union[str, Sequence[str], None] = "77807d29d9d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_telemetry_accumulation_key_type_like",
            "telemetry_accumulation",
            ["key", "data_type", "created_at"],
            unique=False,
            postgresql_ops={"key": "varchar_pattern_ops"},
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            "idx_telemetry_accumulation_key_type_like",
            table_name="telemetry_accumulation",
            postgresql_concurrently=True,
        )
