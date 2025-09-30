"""add_multi_backend_support_to_simple_rollout

Revision ID: 65aa64407982
Revises: 88e5fb059910
Create Date: 2025-09-30 07:03:21.493921

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "65aa64407982"
down_revision: Union[str, Sequence[str], None] = "88e5fb059910"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - add many-to-many relationship for backends."""

    op.create_table(
        "simple_rollout_experiment_config_backends",
        sa.Column("experiment_config_id", sa.String(36), nullable=False),
        sa.Column("backend_id", sa.String(36), nullable=False),
        sa.PrimaryKeyConstraint("experiment_config_id", "backend_id"),
        sa.ForeignKeyConstraint(
            ["experiment_config_id"], ["simple_rollout_experiment_configs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["backend_id"], ["openai_compatible_backends.id"], ondelete="CASCADE"
        ),
    )

    op.create_index(
        op.f("ix_simple_rollout_experiment_config_backends_experiment_config_id"),
        "simple_rollout_experiment_config_backends",
        ["experiment_config_id"],
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_config_backends_backend_id"),
        "simple_rollout_experiment_config_backends",
        ["backend_id"],
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            INSERT INTO simple_rollout_experiment_config_backends (experiment_config_id, backend_id)
            SELECT id, openai_compatible_backend_id
            FROM simple_rollout_experiment_configs
            WHERE openai_compatible_backend_id IS NOT NULL
            """
        )
    )

    op.drop_constraint(
        "fk_simple_rollout_experiment_configs__openai_compatible_5df5",
        "simple_rollout_experiment_configs",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_configs_openai_compatible_backend_id"),
        table_name="simple_rollout_experiment_configs",
    )
    op.drop_column("simple_rollout_experiment_configs", "openai_compatible_backend_id")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "simple_rollout_experiment_configs",
        sa.Column("openai_compatible_backend_id", sa.String(36), nullable=True),
    )
    op.create_index(
        op.f("ix_simple_rollout_experiment_configs_openai_compatible_backend_id"),
        "simple_rollout_experiment_configs",
        ["openai_compatible_backend_id"],
    )
    op.create_foreign_key(
        "fk_simple_rollout_experiment_configs__openai_compatible_5df5",
        "simple_rollout_experiment_configs",
        "openai_compatible_backends",
        ["openai_compatible_backend_id"],
        ["id"],
    )

    op.drop_index(
        op.f("ix_simple_rollout_experiment_config_backends_backend_id"),
        table_name="simple_rollout_experiment_config_backends",
    )
    op.drop_index(
        op.f("ix_simple_rollout_experiment_config_backends_experiment_config_id"),
        table_name="simple_rollout_experiment_config_backends",
    )
    op.drop_table("simple_rollout_experiment_config_backends")
