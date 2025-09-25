"""add investigators schemas

Revision ID: 198c1cd4584f
Revises: e4255c1640a7
Create Date: 2025-09-23 11:28:09.329936

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "198c1cd4584f"
down_revision: Union[str, Sequence[str], None] = "e4255c1640a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # Create investigator_workspaces table
    op.create_table(
        "investigator_workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_investigator_workspaces__created_by__users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_investigator_workspaces")),
    )
    op.create_index(
        op.f("ix_investigator_workspaces__created_by"),
        "investigator_workspaces",
        ["created_by"],
        unique=False,
    )

    # Create judge_configs table
    op.create_table(
        "judge_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("rubric", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["investigator_workspaces.id"],
            name=op.f("fk_judge_configs__workspace_id__investigator_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judge_configs")),
    )
    op.create_index(
        op.f("ix_judge_configs__workspace_id"),
        "judge_configs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_judge_configs__deleted_at"),
        "judge_configs",
        ["deleted_at"],
        unique=False,
    )

    # Create openai_compatible_backends table
    op.create_table(
        "openai_compatible_backends",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("api_key", sa.Text(), nullable=True),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["investigator_workspaces.id"],
            name=op.f("fk_openai_compatible_backends__workspace_id__investigator_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_openai_compatible_backends")),
    )
    op.create_index(
        op.f("ix_openai_compatible_backends__workspace_id"),
        "openai_compatible_backends",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_openai_compatible_backends__deleted_at"),
        "openai_compatible_backends",
        ["deleted_at"],
        unique=False,
    )

    # Create experiment_ideas table
    op.create_table(
        "experiment_ideas",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("idea", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["investigator_workspaces.id"],
            name=op.f("fk_experiment_ideas__workspace_id__investigator_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiment_ideas")),
    )
    op.create_index(
        op.f("ix_experiment_ideas__workspace_id"),
        "experiment_ideas",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_experiment_ideas__deleted_at"),
        "experiment_ideas",
        ["deleted_at"],
        unique=False,
    )

    # Create base_contexts table
    op.create_table(
        "base_contexts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("prompt", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["investigator_workspaces.id"],
            name=op.f("fk_base_contexts__workspace_id__investigator_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_base_contexts")),
    )
    op.create_index(
        op.f("ix_base_contexts__workspace_id"),
        "base_contexts",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_base_contexts__deleted_at"),
        "base_contexts",
        ["deleted_at"],
        unique=False,
    )

    # Create counterfactual_experiment_configs table
    op.create_table(
        "counterfactual_experiment_configs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("judge_config_id", sa.String(length=36), nullable=False),
        sa.Column("openai_compatible_backend_id", sa.String(length=36), nullable=False),
        sa.Column("idea_id", sa.String(length=36), nullable=False),
        sa.Column("base_context_id", sa.String(length=36), nullable=False),
        sa.Column("num_counterfactuals", sa.Integer(), nullable=False),
        sa.Column("num_replicas", sa.Integer(), nullable=False),
        sa.Column("max_turns", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["base_context_id"],
            ["base_contexts.id"],
            name=op.f("fk_counterfactual_experiment_configs__base_context_id__base_contexts"),
        ),
        sa.ForeignKeyConstraint(
            ["idea_id"],
            ["experiment_ideas.id"],
            name=op.f("fk_counterfactual_experiment_configs__idea_id__experiment_ideas"),
        ),
        sa.ForeignKeyConstraint(
            ["judge_config_id"],
            ["judge_configs.id"],
            name=op.f("fk_counterfactual_experiment_configs__judge_config_id__judge_configs"),
        ),
        sa.ForeignKeyConstraint(
            ["openai_compatible_backend_id"],
            ["openai_compatible_backends.id"],
            name=op.f(
                "fk_counterfactual_experiment_configs__openai_compatible_backend_id__openai_compatible_backends"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["investigator_workspaces.id"],
            name=op.f(
                "fk_counterfactual_experiment_configs__workspace_id__investigator_workspaces"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counterfactual_experiment_configs")),
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_configs__workspace_id"),
        "counterfactual_experiment_configs",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_configs__judge_config_id"),
        "counterfactual_experiment_configs",
        ["judge_config_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_configs__openai_compatible_backend_id"),
        "counterfactual_experiment_configs",
        ["openai_compatible_backend_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_configs__idea_id"),
        "counterfactual_experiment_configs",
        ["idea_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_configs__base_context_id"),
        "counterfactual_experiment_configs",
        ["base_context_id"],
        unique=False,
    )

    # Create counterfactual_experiment_results table
    op.create_table(
        "counterfactual_experiment_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_config_id", sa.String(length=36), nullable=False),
        sa.Column("collection_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("agent_run_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("counterfactual_idea_output", sa.Text(), nullable=True),
        sa.Column(
            "counterfactual_context_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "parsed_counterfactual_ideas", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "counterfactual_policy_configs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("base_policy_config", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_counterfactual_experiment_results__collection_id__collections"),
        ),
        sa.ForeignKeyConstraint(
            ["experiment_config_id"],
            ["counterfactual_experiment_configs.id"],
            name=op.f(
                "fk_counterfactual_experiment_results__experiment_config_id__counterfactual_experiment_configs"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_counterfactual_experiment_results")),
        sa.UniqueConstraint(
            "experiment_config_id",
            name=op.f("uq_counterfactual_experiment_results__experiment_config_id"),
        ),
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_results__experiment_config_id"),
        "counterfactual_experiment_results",
        ["experiment_config_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_counterfactual_experiment_results__collection_id"),
        "counterfactual_experiment_results",
        ["collection_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""

    # Drop tables in reverse order (respecting foreign key dependencies)
    op.drop_table("counterfactual_experiment_results")
    op.drop_table("counterfactual_experiment_configs")
    op.drop_table("base_contexts")
    op.drop_table("experiment_ideas")
    op.drop_table("openai_compatible_backends")
    op.drop_table("judge_configs")
    op.drop_table("investigator_workspaces")
