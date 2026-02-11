"""add metadata registry

Revision ID: b3f7a2c8d910
Revises: 74aec36e7f83
Create Date: 2026-02-09 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3f7a2c8d910"
down_revision: Union[str, Sequence[str], None] = "74aec36e7f83"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create metadata_observations table and metadata_value_stats materialized view."""
    # Create the metadata_observations table
    op.create_table(
        "metadata_observations",
        sa.Column(
            "agent_run_id",
            sa.String(36),
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("json_path", sa.Text, nullable=False),
        sa.Column("value_hash", sa.String(32), nullable=False),
        sa.Column("value_type", sa.Text, nullable=False),
        sa.Column("collection_id", sa.String(36), sa.ForeignKey("collections.id"), nullable=False),
        sa.Column("value_text", sa.Text, nullable=False),
        sa.Column("value_numeric", sa.Numeric, nullable=True),
        sa.Column("observed_at", sa.DateTime, nullable=False),
        sa.PrimaryKeyConstraint("agent_run_id", "json_path", "value_hash", "value_type"),
    )

    # Indexes on the table
    op.create_index(
        "ix_metadata_obs__collection_id",
        "metadata_observations",
        ["collection_id"],
    )
    op.create_index(
        "ix_metadata_obs__collection_path",
        "metadata_observations",
        ["collection_id", "json_path"],
    )
    op.create_index(
        "ix_metadata_obs__collection_path_hash",
        "metadata_observations",
        ["collection_id", "json_path", "value_hash"],
    )
    op.create_index(
        "ix_metadata_obs__collection_path_type_numeric",
        "metadata_observations",
        ["collection_id", "json_path", "value_type"],
        postgresql_where=sa.text("value_numeric IS NOT NULL"),
    )

    # Create the materialized view
    op.execute("""
        CREATE MATERIALIZED VIEW metadata_value_stats AS
        SELECT
            collection_id,
            json_path,
            value_text,
            value_hash,
            value_type,
            COUNT(*)::integer AS count,
            MIN(observed_at) AS first_seen_at,
            MAX(observed_at) AS last_seen_at,
            value_numeric
        FROM metadata_observations
        GROUP BY collection_id, json_path, value_text, value_hash, value_type, value_numeric
    """)

    # Unique index required for REFRESH CONCURRENTLY
    op.execute("""
        CREATE UNIQUE INDEX ix_mvs__unique
        ON metadata_value_stats (collection_id, json_path, value_hash, value_type)
    """)
    op.execute("""
        CREATE INDEX ix_mvs__collection_path_count
        ON metadata_value_stats (collection_id, json_path, count DESC)
    """)
    op.execute("""
        CREATE INDEX ix_mvs__collection_path
        ON metadata_value_stats (collection_id, json_path)
    """)


def downgrade() -> None:
    """Drop materialized view and table."""
    op.execute("DROP MATERIALIZED VIEW IF EXISTS metadata_value_stats")
    op.drop_table("metadata_observations")
