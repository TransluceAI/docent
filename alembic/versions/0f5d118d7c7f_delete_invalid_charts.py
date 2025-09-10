"""Delete invalid charts

Revision ID: 0f5d118d7c7f
Revises: 44aa3e803cca
Create Date: 2025-09-10 12:56:04.166678

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0f5d118d7c7f"
down_revision: Union[str, Sequence[str], None] = "44aa3e803cca"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Before overhauling judge output schemas, we allowed more keys.
# Now we only allow: COUNT(ar.id), ar.metadata_json->>*, jr.output->>*
invalid_chart_keys = [
    "rc.centroid",
    "r.rubric_text",
    "COUNT(jr.id)",
    "COUNT(jrc.id)",
    "COUNT(jrc.id)_normalize_by_run",
    "COUNT(jr.id)_normalize_by_run",
    "COUNT(ar.id)_normalize_by_run",
]


def upgrade() -> None:
    """Upgrade schema."""
    keys_param = sa.bindparam("keys", expanding=True, type_=sa.Text())
    stmt = sa.text(
        """
        DELETE FROM charts
        WHERE series_key IN :keys
           OR x_key IN :keys
           OR y_key IN :keys
           OR rubric_filter IS NOT NULL
        """
    ).bindparams(keys_param)
    op.get_bind().execute(stmt, {"keys": invalid_chart_keys})

    op.drop_column("charts", "rubric_filter")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("charts", sa.Column("rubric_filter", sa.Text(), nullable=True))
