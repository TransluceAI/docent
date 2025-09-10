from copy import deepcopy
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.filters import ComplexFilter, parse_filter_dict
from docent_core.docent.db.schemas.tables import (
    TABLE_COLLECTION,
    TABLE_USER,
    SQLACollection,
    SQLAUser,
)

TABLE_CHART = "charts"


class SQLAChart(SQLABase):
    __tablename__ = TABLE_CHART

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)

    # Foreign keys
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    created_by = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True
    )

    # Chart configuration
    series_key = mapped_column(Text, nullable=True)
    x_key = mapped_column(Text, nullable=True)
    y_key = mapped_column(Text, nullable=True)

    # If set, chart only shows data from these runs
    runs_filter_dict = mapped_column(JSONB, nullable=True)

    # Chart visualization settings
    chart_type = mapped_column(Text, nullable=False, default="bar")  # 'bar', 'line', 'table'

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    updated_at = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )

    # Relationships
    creator: Mapped["SQLAUser"] = relationship("SQLAUser", lazy="select")
    collection: Mapped["SQLACollection"] = relationship("SQLACollection", lazy="select")

    @property
    def runs_filter(self) -> ComplexFilter | None:
        if self.runs_filter_dict is None:
            return None
        result = parse_filter_dict(deepcopy(self.runs_filter_dict))
        assert isinstance(result, ComplexFilter)
        return result
