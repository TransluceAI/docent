from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import (
    TABLE_COLLECTION,
    TABLE_USER,
    SQLACollection,
    SQLAUser,
)

TABLE_DATA_TABLE = "data_tables"


class SQLADataTable(SQLABase):
    __tablename__ = TABLE_DATA_TABLE

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)
    dql = mapped_column(Text, nullable=False)
    state_json = mapped_column(JSONB, nullable=True)

    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    created_by = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    updated_at = mapped_column(
        DateTime,
        default=lambda: datetime.now(UTC).replace(tzinfo=None),
        onupdate=lambda: datetime.now(UTC).replace(tzinfo=None),
        nullable=False,
    )

    creator: Mapped["SQLAUser"] = relationship("SQLAUser", lazy="select")
    collection: Mapped["SQLACollection"] = relationship("SQLACollection", lazy="select")
