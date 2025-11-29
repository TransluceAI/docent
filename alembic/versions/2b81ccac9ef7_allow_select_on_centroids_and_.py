"""allow select on centroids and assignments for DQL

Revision ID: 2b81ccac9ef7
Revises: 1046850ac3c7
Create Date: 2025-11-29 17:56:10.729425

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b81ccac9ef7"
down_revision: Union[str, Sequence[str], None] = "1046850ac3c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DQL_ROLE = "docent_dql_reader"


def upgrade() -> None:
    """Allow the DQL role to read the rubric centroids and judge result centroids tables."""
    op.execute(f"GRANT SELECT ON rubric_centroids TO {_DQL_ROLE};")
    op.execute(f"GRANT SELECT ON judge_result_centroids TO {_DQL_ROLE};")


def downgrade() -> None:
    """Revoke the DQL role's ability to read the rubric centroids and judge result centroids tables."""
    op.execute(f"REVOKE SELECT ON rubric_centroids FROM {_DQL_ROLE};")
    op.execute(f"REVOKE SELECT ON judge_result_centroids FROM {_DQL_ROLE};")
