from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column

from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import TABLE_COLLECTION

TABLE_REFINEMENT_SESSION = "refinement_sessions"


class SQLARefinementSession(SQLABase):
    __tablename__ = TABLE_REFINEMENT_SESSION

    id = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    # Not a foreign key bc we don't want our sessions linked to rubric uniqueness
    rubric_id = mapped_column(String(36), nullable=False, index=True)

    # JSON field to store all messages
    messages = mapped_column(JSONB, nullable=False, default=list)

    updated_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False, index=True
    )
