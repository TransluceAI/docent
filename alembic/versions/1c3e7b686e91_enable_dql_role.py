"""Enable Docent Query Language read only role.

Revision ID: 1c3e7b686e91
Revises: 2ce051f8d590
Create Date: 2024-11-24 00:00:00.000000

"""

import os
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1c3e7b686e91"
down_revision: Union[str, Sequence[str], None] = "2ce051f8d590"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DQL_ROLE = "docent_dql_reader"


def upgrade() -> None:
    """Install the read-only role used by DQL."""

    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{_DQL_ROLE}') THEN
                CREATE ROLE {_DQL_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )

    op.execute(f"GRANT USAGE ON SCHEMA public TO {_DQL_ROLE};")
    op.execute(
        f"""
        GRANT SELECT ON
            agent_runs,
            transcripts,
            transcript_groups,
            judge_results
        TO {_DQL_ROLE};
        """
    )

    # Grant the DQL role so SET ROLE docent_dql_reader succeeds when DQL sessions need to drop privileges
    # INHERIT FALSE keeps the base user from automatically gaining those read-only privileges outside of SET ROLE
    default_user = os.getenv("DOCENT_PG_USER")
    if default_user:
        connection = op.get_bind()
        connection.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    default_user_name TEXT := :default_user;
                    role_name TEXT := :role_name;
                BEGIN
                    EXECUTE format('GRANT %I TO %I', role_name, default_user_name);
                END
                $$;
                """
            ),
            {"default_user": default_user, "role_name": _DQL_ROLE},
        )


def downgrade() -> None:
    """Remove the DQL role."""

    # Revoke the DQL role from the default user
    default_user = os.getenv("DOCENT_PG_USER")
    if default_user:
        connection = op.get_bind()
        connection.execute(
            sa.text(
                """
                DO $$
                DECLARE
                    default_user_name TEXT := :default_user;
                    role_name TEXT := :role_name;
                BEGIN
                    EXECUTE format('REVOKE %I FROM %I', role_name, default_user_name);
                END
                $$;
                """
            ),
            {"default_user": default_user, "role_name": _DQL_ROLE},
        )

    op.execute(
        f"""
        REVOKE SELECT ON
            agent_runs,
            transcripts,
            transcript_groups,
            judge_results
        FROM {_DQL_ROLE};
        """
    )
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {_DQL_ROLE};")

    op.execute(f"DROP ROLE IF EXISTS {_DQL_ROLE};")
