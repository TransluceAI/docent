"""add separate table for ingestion payloads

Revision ID: 1046850ac3c7
Revises: 06402b04a191
Create Date: 2025-11-24 14:06:19.381313

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1046850ac3c7"
down_revision: Union[str, Sequence[str], None] = "06402b04a191"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "ingestion_payloads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("content_encoding", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_ingestion_payloads__job_id__jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_payloads")),
    )
    op.create_index(
        op.f("ix_ingestion_payloads__job_id"), "ingestion_payloads", ["job_id"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_ingestion_payloads__job_id"), table_name="ingestion_payloads")
    op.drop_table("ingestion_payloads")
