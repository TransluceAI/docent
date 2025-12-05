from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from docent.data_models.citation import InlineCitation
from docent.data_models.judge import Label
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import TABLE_AGENT_RUN, TABLE_COLLECTION, TABLE_USER

TABLE_LABEL = "labels"
TABLE_LABEL_SET = "label_sets"
TABLE_LABEL_SET_RUBRIC = "label_set_rubrics"
TABLE_ANNOTATION = "annotations"
TABLE_TAG = "tags"


class SQLALabel(SQLABase):
    """Labels table - stores individual labels for agent runs."""

    __tablename__ = TABLE_LABEL
    __table_args__ = (
        UniqueConstraint(
            "agent_run_id",
            "label_set_id",
            name="uq_label_agent_run_label_set",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    label_set_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_LABEL_SET}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_AGENT_RUN}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    @classmethod
    def from_pydantic(cls, label: Label) -> "SQLALabel":
        return cls(
            id=label.id,
            label_set_id=label.label_set_id,
            agent_run_id=label.agent_run_id,
            label_value=label.label_value,
        )

    def to_pydantic(self) -> Label:
        return Label(
            id=self.id,
            label_set_id=self.label_set_id,
            agent_run_id=self.agent_run_id,
            label_value=self.label_value,
        )


class LabelSet(BaseModel):
    id: str
    name: str
    description: str | None
    label_schema: dict[str, Any]


class SQLALabelSet(SQLABase):
    """Label set table - defines a schema for labels."""

    __tablename__ = TABLE_LABEL_SET

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_COLLECTION}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    label_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    @property
    def label_schema_no_reqs(self) -> dict[str, Any]:
        """Get the label schema without the 'required' field."""
        label_schema = self.label_schema.copy()
        label_schema.pop("required", None)
        return label_schema

    def to_pydantic(self) -> LabelSet:
        return LabelSet(
            id=self.id,
            name=self.name,
            description=self.description,
            label_schema=self.label_schema,
        )


class Annotation(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_email: str
    collection_id: str
    agent_run_id: str
    citations: list[InlineCitation]
    created_at: datetime
    content: str


class SQLAAnnotation(SQLABase):
    """Annotations table - stores annotations for agent runs."""

    __tablename__ = TABLE_ANNOTATION

    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), index=True)
    collection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_COLLECTION}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_AGENT_RUN}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    citations: Mapped[list[InlineCitation]] = mapped_column(JSONB, nullable=False)

    content: Mapped[str] = mapped_column(Text, nullable=False)

    def to_pydantic(self, user_email: str) -> Annotation:
        return Annotation(
            id=self.id,
            user_email=user_email,
            collection_id=self.collection_id,
            agent_run_id=self.agent_run_id,
            citations=[InlineCitation.model_validate(citation) for citation in self.citations],
            created_at=self.created_at,
            content=self.content,
        )


class SQLATag(SQLABase):
    """Tags table - stores quick tags on agent runs."""

    __tablename__ = TABLE_TAG
    __table_args__ = (
        Index("ix_tags_collection_value", "collection_id", "value"),
        Index("ix_tags_collection_agent_run", "collection_id", "agent_run_id"),
        UniqueConstraint(
            "agent_run_id",
            "value",
            name="uq_tags_agent_run_value",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_COLLECTION}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_AGENT_RUN}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    value: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_USER}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
