"""modify result enum

Revision ID: 7a05c9d5804c
Revises: 9b87d6874efc
Create Date: 2025-12-09 14:33:13.077032

"""

from typing import Sequence, Union

from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a05c9d5804c"
down_revision: Union[str, Sequence[str], None] = "9b87d6874efc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create the new enum type
    new_result_enum = postgresql.ENUM("DIRECT_RESULT", "FAILURE", name="result_type")
    new_result_enum.create(op.get_bind(), checkfirst=True)

    # For each table: drop default, change type

    # judge_result_centroids
    op.alter_column("judge_result_centroids", "result_type", server_default=None)
    op.execute(
        """
        ALTER TABLE judge_result_centroids
        ALTER COLUMN result_type TYPE result_type
        USING CASE
            WHEN result_type::text = 'DIRECT_RESULT' THEN 'DIRECT_RESULT'::result_type
            WHEN result_type::text = 'NEAR_MISS' THEN 'FAILURE'::result_type
        END
    """
    )

    # judge_results
    op.alter_column("judge_results", "result_type", server_default=None)
    op.execute(
        """
        ALTER TABLE judge_results
        ALTER COLUMN result_type TYPE result_type
        USING CASE
            WHEN result_type::text = 'DIRECT_RESULT' THEN 'DIRECT_RESULT'::result_type
            WHEN result_type::text = 'NEAR_MISS' THEN 'FAILURE'::result_type
        END
    """
    )

    # rubric_centroids
    op.alter_column("rubric_centroids", "result_type", server_default=None)
    op.execute(
        """
        ALTER TABLE rubric_centroids
        ALTER COLUMN result_type TYPE result_type
        USING CASE
            WHEN result_type::text = 'DIRECT_RESULT' THEN 'DIRECT_RESULT'::result_type
            WHEN result_type::text = 'NEAR_MISS' THEN 'FAILURE'::result_type
        END
    """
    )

    # Drop the old enum type
    op.execute("DROP TYPE IF EXISTS resulttype")


def downgrade() -> None:
    """Downgrade schema."""
