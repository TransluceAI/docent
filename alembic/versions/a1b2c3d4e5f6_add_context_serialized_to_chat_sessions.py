"""Add context_serialized to chat_sessions

Revision ID: a1b2c3d4e5f6
Revises: fd41be117f90
Create Date: 2025-11-05 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "fd41be117f90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "chat_sessions",
        sa.Column("context_serialized", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.alter_column(
        "chat_sessions",
        "agent_run_id",
        existing_type=sa.String(36),
        nullable=True,
    )

    # Delete chat sessions with null agent_run_id before adding the constraint
    # These are orphaned sessions that cannot be used
    op.execute(
        """
        DELETE FROM chat_sessions
        WHERE agent_run_id IS NULL
        """
    )

    op.create_check_constraint(
        "chat_sessions_context_or_run",
        "chat_sessions",
        "(agent_run_id IS NOT NULL AND context_serialized IS NULL) OR (agent_run_id IS NULL AND context_serialized IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("chat_sessions_context_or_run", "chat_sessions", type_="check")

    op.execute(
        """
        DELETE FROM chat_sessions
        WHERE agent_run_id IS NULL
        """
    )
    op.alter_column(
        "chat_sessions",
        "agent_run_id",
        existing_type=sa.String(36),
        nullable=False,
    )

    op.drop_column("chat_sessions", "context_serialized")
