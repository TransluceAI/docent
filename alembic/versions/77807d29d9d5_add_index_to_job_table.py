"""add index to job table

Revision ID: 77807d29d9d5
Revises: a1b2c3d4e5f6
Create Date: 2025-11-18 12:52:04.863292

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "77807d29d9d5"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_jobs_job_json_gin",
            "jobs",
            ["job_json"],
            unique=False,
            if_not_exists=True,
            postgresql_using="gin",
            postgresql_ops={"job_json": "jsonb_path_ops"},
            postgresql_concurrently=True,
        )
        op.create_index(
            "idx_jobs_type_status_created_at",
            "jobs",
            ["type", "status", "created_at"],
            unique=False,
            if_not_exists=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.get_context().autocommit_block():
        op.drop_index(
            "idx_jobs_type_status_created_at",
            table_name="jobs",
            postgresql_concurrently=True,
        )
        op.drop_index(
            "idx_jobs_job_json_gin",
            table_name="jobs",
            postgresql_concurrently=True,
        )
