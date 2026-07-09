"""add hodoscope analyses

Revision ID: a2e2b7c9142a
Revises: e4255c1640a7
Create Date: 2026-07-09 13:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2e2b7c9142a"
down_revision: Union[str, Sequence[str], None] = "e4255c1640a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "hodoscope_analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("artifact_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("projection_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_hodoscope_analyses__collection_id__collections"),
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_hodoscope_analyses__job_id__jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hodoscope_analyses")),
    )
    op.create_index(
        op.f("ix_hodoscope_analyses_collection_id"),
        "hodoscope_analyses",
        ["collection_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hodoscope_analyses_job_id"),
        "hodoscope_analyses",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_hodoscope_analyses_status"),
        "hodoscope_analyses",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_hodoscope_analyses_collection_created",
        "hodoscope_analyses",
        ["collection_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("idx_hodoscope_analyses_collection_created", table_name="hodoscope_analyses")
    op.drop_index(op.f("ix_hodoscope_analyses_status"), table_name="hodoscope_analyses")
    op.drop_index(op.f("ix_hodoscope_analyses_job_id"), table_name="hodoscope_analyses")
    op.drop_index(op.f("ix_hodoscope_analyses_collection_id"), table_name="hodoscope_analyses")
    op.drop_table("hodoscope_analyses")
