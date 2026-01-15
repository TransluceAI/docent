from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import TABLE_COLLECTION, TABLE_USER

TABLE_RESULT_SET = "result_sets"
TABLE_RESULT = "results"


class SQLAResultSet(SQLABase):
    """Stores a named set of LLM analysis results."""

    __tablename__ = TABLE_RESULT_SET

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False)
    collection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    name: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_schema: Mapped[dict[str, Any]] = mapped_column("output_schema", JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_result_set_collection_name_unique",
            "collection_id",
            "name",
            unique=True,
            postgresql_where="name IS NOT NULL",
        ),
    )

    results: Mapped[list["SQLAResult"]] = relationship(
        "SQLAResult",
        back_populates="result_set",
        cascade="all, delete-orphan",
    )


class SQLAResult(SQLABase):
    """Stores an individual LLM analysis result."""

    __tablename__ = TABLE_RESULT

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    result_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_RESULT_SET}.id", ondelete="CASCADE"),
        nullable=False,
    )

    # LLMRequest data (LLMContextSpec is stored as JSONB for efficiency)
    llm_context_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Segments are either strings or {"alias": "R0"} dicts
    prompt_segments: Mapped[list[str | dict[str, str]]] = mapped_column(JSONB, nullable=False)
    user_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Output
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Token/cost tracking
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    __table_args__ = (Index("ix_results__result_set_id_created_at", "result_set_id", "created_at"),)

    result_set: Mapped["SQLAResultSet"] = relationship(
        "SQLAResultSet",
        back_populates="results",
    )
