"""add_simple_rollout_experiment_tables

Revision ID: 88e5fb059910
Revises: 863c43b0ddd3
Create Date: 2025-09-27 11:45:20.132072

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "88e5fb059910"
down_revision: Union[str, Sequence[str], None] = "863c43b0ddd3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create simple_rollout_experiment_configs table
    op.create_table(
        "simple_rollout_experiment_configs",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("judge_config_id", sa.String(36), nullable=True),  # Optional for simple rollout
        sa.Column("openai_compatible_backend_id", sa.String(36), nullable=False),
        sa.Column("base_context_id", sa.String(36), nullable=False),
        sa.Column("num_replicas", sa.Integer(), nullable=False, default=1),
        sa.Column("max_turns", sa.Integer(), nullable=False, default=1),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workspace_id"], ["investigator_workspaces.id"]),
        sa.ForeignKeyConstraint(["judge_config_id"], ["judge_configs.id"]),
        sa.ForeignKeyConstraint(
            ["openai_compatible_backend_id"], ["openai_compatible_backends.id"]
        ),
        sa.ForeignKeyConstraint(["base_context_id"], ["base_contexts.id"]),
    )

    # Create indexes for simple_rollout_experiment_configs
    op.create_index(
        op.f("ix_simple_rollout_experiment_configs_workspace_id"),
        "simple_rollout_experiment_configs",
        ["workspace_id"],
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_configs_judge_config_id"),
        "simple_rollout_experiment_configs",
        ["judge_config_id"],
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_configs_openai_compatible_backend_id"),
        "simple_rollout_experiment_configs",
        ["openai_compatible_backend_id"],
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_configs_base_context_id"),
        "simple_rollout_experiment_configs",
        ["base_context_id"],
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_configs_deleted_at"),
        "simple_rollout_experiment_configs",
        ["deleted_at"],
    )

    # Create simple_rollout_experiment_results table
    op.create_table(
        "simple_rollout_experiment_results",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("experiment_config_id", sa.String(36), nullable=False),
        sa.Column("collection_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(50), nullable=False, default="in_progress"),
        sa.Column("progress", sa.Integer(), nullable=False, default=0),
        sa.Column("agent_run_metadata", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("base_policy_config", sa.dialects.postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["experiment_config_id"], ["simple_rollout_experiment_configs.id"]),
        sa.ForeignKeyConstraint(["collection_id"], ["collections.id"]),
        sa.UniqueConstraint("experiment_config_id"),  # Enforce one-to-one relationship
    )

    # Create indexes for simple_rollout_experiment_results
    op.create_index(
        op.f("ix_simple_rollout_experiment_results_experiment_config_id"),
        "simple_rollout_experiment_results",
        ["experiment_config_id"],
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_results_collection_id"),
        "simple_rollout_experiment_results",
        ["collection_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes for simple_rollout_experiment_results
    op.drop_index(
        op.f("ix_simple_rollout_experiment_results_collection_id"),
        table_name="simple_rollout_experiment_results",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_results_experiment_config_id"),
        table_name="simple_rollout_experiment_results",
    )

    # Drop simple_rollout_experiment_results table
    op.drop_table("simple_rollout_experiment_results")

    # Drop indexes for simple_rollout_experiment_configs
    op.drop_index(
        op.f("ix_simple_rollout_experiment_configs_deleted_at"),
        table_name="simple_rollout_experiment_configs",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_configs_base_context_id"),
        table_name="simple_rollout_experiment_configs",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_configs_openai_compatible_backend_id"),
        table_name="simple_rollout_experiment_configs",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_configs_judge_config_id"),
        table_name="simple_rollout_experiment_configs",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_configs_workspace_id"),
        table_name="simple_rollout_experiment_configs",
    )

    # Drop simple_rollout_experiment_configs table
    op.drop_table("simple_rollout_experiment_configs")
