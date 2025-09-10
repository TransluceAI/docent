"""JSON judge output

Revision ID: bb386feb1740
Revises: 43165c6783d2
Create Date: 2025-09-04 14:33:36.968100

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb386feb1740"
down_revision: Union[str, Sequence[str], None] = "43165c6783d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create rubrics.output_schema as nullable first
    op.add_column(
        "rubrics",
        sa.Column(
            "output_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    # Backfill existing rows to the application default where NULL
    op.execute(
        sa.text(
            (
                "UPDATE rubrics "
                "SET output_schema = "
                '\'{"type": "object", "properties": {"explanation": {"type": "string", "citations": true}, "label": {"type": "string", "enum": ["match", "no match"]}}}\'::jsonb '
                "WHERE output_schema IS NULL"
            )
        )
    )
    # Enforce NOT NULL after backfill
    op.alter_column(
        "rubrics",
        "output_schema",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )

    # Add CASCADE delete to judge_result_centroids foreign key constraint (need this later when deleting judge results)
    op.drop_constraint(
        "fk_judge_result_centroids__judge_result_id__judge_results",
        "judge_result_centroids",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_judge_result_centroids__judge_result_id__judge_results",
        "judge_result_centroids",
        "judge_results",
        ["judge_result_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Add CASCADE delete to chat_sessions foreign key constraint for judge_result_id
    op.drop_constraint("fk_chat_sessions_judge_result_id", "chat_sessions", type_="foreignkey")
    op.create_foreign_key(
        "fk_chat_sessions_judge_result_id",
        "chat_sessions",
        "judge_results",
        ["judge_result_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # Create judge_results.output as nullable first
    op.add_column(
        "judge_results", sa.Column("output", postgresql.JSONB(astext_type=sa.Text()), nullable=True)
    )
    # Backfill: collapse multiple judge_results per (agent_run_id, rubric_id, rubric_version) into a single row.
    # - explanation: concatenation of all non-null values in the group (separated by blank lines).
    # - label: 'no match' only if there was exactly one row and its value was NULL; otherwise 'match'.
    op.execute(
        sa.text(
            """
            WITH agg AS (
                SELECT
                    agent_run_id,
                    rubric_id,
                    rubric_version,
                    MIN(id) AS keep_id,
                    COUNT(*) AS cnt,
                    COUNT(value) AS cnt_value_nonnull,
                    STRING_AGG(value, E'\n\n') FILTER (WHERE value IS NOT NULL) AS explanation
                FROM judge_results
                GROUP BY agent_run_id, rubric_id, rubric_version
            )
            UPDATE judge_results j
            SET output = jsonb_build_object(
                'explanation', COALESCE(agg.explanation, ''),
                'label', CASE WHEN agg.cnt = 1 AND agg.cnt_value_nonnull = 0 THEN 'no match' ELSE 'match' END
            )
            FROM agg
            WHERE j.id = agg.keep_id
            """
        )
    )
    # Delete duplicate rows, keeping the MIN(id) per group
    op.execute(
        sa.text(
            """
            WITH keep AS (
                SELECT MIN(id) AS keep_id, agent_run_id, rubric_id, rubric_version
                FROM judge_results
                GROUP BY agent_run_id, rubric_id, rubric_version
            )
            DELETE FROM judge_results j
            USING keep
            WHERE j.agent_run_id = keep.agent_run_id
              AND j.rubric_id = keep.rubric_id
              AND j.rubric_version = keep.rubric_version
              AND j.id != keep.keep_id
            """
        )
    )
    # Enforce NOT NULL after backfill
    op.alter_column(
        "judge_results",
        "output",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        nullable=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Restore original foreign key constraint without CASCADE
    op.drop_constraint(
        "fk_judge_result_centroids__judge_result_id__judge_results",
        "judge_result_centroids",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_judge_result_centroids__judge_result_id__judge_results",
        "judge_result_centroids",
        "judge_results",
        ["judge_result_id"],
        ["id"],
    )

    op.drop_column("rubrics", "output_schema")
    op.drop_column("judge_results", "output")
