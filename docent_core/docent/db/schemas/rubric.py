from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util.logger import get_logger
from docent_core.docent.db.schemas.label import TABLE_LABEL, SQLALabel

if TYPE_CHECKING:
    from docent_core.docent.db.schemas.refinement import SQLARefinementAgentSession

from docent.judges import JudgeResult, JudgeVariant, ResultType, Rubric
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import TABLE_AGENT_RUN, TABLE_COLLECTION

TABLE_RUBRIC = "rubrics"
TABLE_JUDGE_RESULT = "judge_results"
TABLE_JUDGE_RUN_LABEL = "judge_run_labels"
TABLE_RUBRIC_CENTROID = "rubric_centroids"
TABLE_JUDGE_RESULT_CENTROIDS = "judge_result_centroids"
TABLE_JUDGE_REFLECTION = "judge_reflections"

logger = get_logger(__name__)

RESULT_TYPE_ENUM = Enum(ResultType, name="resulttype")


class SQLARubric(SQLABase):
    __tablename__ = TABLE_RUBRIC

    id: Mapped[str] = mapped_column(String(36), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    collection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    rubric_text: Mapped[str] = mapped_column(Text, nullable=False)
    # Nullable for bwd compat
    n_rollouts_per_input: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1)
    # Nullable for bwd compat
    judge_variant: Mapped[JudgeVariant | None] = mapped_column(
        Enum(JudgeVariant), nullable=True, default=JudgeVariant.MAJORITY
    )

    # Nullable for bwd compat
    system_prompt_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable for bwd compat
    citation_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Follows https://json-schema.org standard
    output_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    judge_model: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # --- START DEPRECATED ---
    high_level_description: Mapped[str] = mapped_column(Text, nullable=True)
    inclusion_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=True)
    exclusion_rules: Mapped[list[str]] = mapped_column(JSONB, nullable=True)
    # --- END DEPRECATED ---

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Composite primary key constraint
    __table_args__ = (PrimaryKeyConstraint("id", "version"),)

    # Relationship to centroids with cascade delete
    centroids: Mapped[list["SQLARubricCentroid"]] = relationship(
        "SQLARubricCentroid",
        back_populates="rubric",
        cascade="all, delete-orphan",
    )
    # Relationship to judge results with cascade delete
    judge_results: Mapped[list["SQLAJudgeResult"]] = relationship(
        "SQLAJudgeResult",
        back_populates="rubric",
        cascade="all, delete-orphan",
    )

    # Relationship to refinement sessions with cascade delete
    refinement_sessions: Mapped[list["SQLARefinementAgentSession"]] = relationship(
        "SQLARefinementAgentSession",
        back_populates="rubric",
        cascade="all, delete-orphan",
    )

    @classmethod
    def from_pydantic(cls, rubric: Rubric, collection_id: str) -> "SQLARubric":
        return cls(
            id=rubric.id,
            version=rubric.version,
            collection_id=collection_id,
            rubric_text=rubric.rubric_text,
            n_rollouts_per_input=rubric.n_rollouts_per_input,
            judge_variant=rubric.judge_variant,
            system_prompt_template=rubric.system_prompt_template,
            citation_instructions=rubric.citation_instructions,
            output_schema=rubric.output_schema,
            judge_model=rubric.judge_model.model_dump(),
        )

    def to_pydantic(self) -> Rubric:
        jm = ModelOption.model_validate(self.judge_model)

        kwargs: dict[str, Any] = {
            "id": self.id,
            "version": self.version,
            "rubric_text": self.rubric_text,
            "output_schema": self.output_schema,
            "judge_model": jm,
        }

        # Necessary for backwards compatibility
        # i.e., do not fill the field if they don't exist in the DB; use Pydantic defaults.
        if self.n_rollouts_per_input is not None:
            kwargs["n_rollouts_per_input"] = self.n_rollouts_per_input
        if self.judge_variant is not None:
            kwargs["judge_variant"] = self.judge_variant
        if self.system_prompt_template is not None:
            kwargs["system_prompt_template"] = self.system_prompt_template
        if self.citation_instructions is not None:
            kwargs["citation_instructions"] = self.citation_instructions

        return Rubric(**kwargs)

    @property
    def short_name(self) -> str:
        text = self.rubric_text.strip()
        if not text:
            return "Untitled rubric"
        first_line = text.split("\n")[0]
        first_line_truncate_len = 50
        if len(first_line) > first_line_truncate_len:
            return first_line[:first_line_truncate_len] + "..."
        return first_line


class SQLAJudgeRunLabel(SQLABase):
    __tablename__ = TABLE_JUDGE_RUN_LABEL

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_AGENT_RUN}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rubric_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    label: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    #### DEPRECATED METHODS (JudgeRunLabel does not exist) ###

    # @classmethod
    # def from_pydantic(cls, judge_run_label: JudgeRunLabel) -> "SQLAJudgeRunLabel":
    #     return cls(
    #         id=judge_run_label.id,
    #         agent_run_id=judge_run_label.agent_run_id,
    #         rubric_id=judge_run_label.rubric_id,
    #         label=judge_run_label.label,
    #     )

    # def to_pydantic(self) -> JudgeRunLabel:
    #     return JudgeRunLabel(
    #         id=self.id,
    #         agent_run_id=self.agent_run_id,
    #         rubric_id=self.rubric_id,
    #         label=self.label,
    #     )


class SQLAJudgeResult(SQLABase):
    __tablename__ = TABLE_JUDGE_RESULT

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    rubric_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)

    # Outputs
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    result_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    result_type: Mapped[ResultType] = mapped_column(RESULT_TYPE_ENUM, nullable=False)

    # Deprecated
    value: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Composite foreign key constraint
    __table_args__ = (
        ForeignKeyConstraint(
            ["rubric_id", "rubric_version"],
            [f"{TABLE_RUBRIC}.id", f"{TABLE_RUBRIC}.version"],
        ),
    )

    # Relationship back to rubric
    rubric: Mapped["SQLARubric"] = relationship(
        "SQLARubric",
        back_populates="judge_results",
        foreign_keys=[rubric_id, rubric_version],
    )
    # Relationship to centroids through junction table
    centroid_assignments: Mapped[list["SQLAJudgeResultCentroid"]] = relationship(
        "SQLAJudgeResultCentroid",
        back_populates="judge_result",
        cascade="all, delete-orphan",
    )

    @classmethod
    def from_pydantic(cls, judge_result: JudgeResult) -> "SQLAJudgeResult":
        return cls(
            id=judge_result.id,
            agent_run_id=judge_result.agent_run_id,
            rubric_id=judge_result.rubric_id,
            rubric_version=judge_result.rubric_version,
            output=judge_result.output,
            result_metadata=judge_result.result_metadata,
            result_type=judge_result.result_type,
            value=judge_result.value,
        )

    def to_pydantic(self) -> JudgeResult:
        return JudgeResult(
            id=self.id,
            agent_run_id=self.agent_run_id,
            rubric_id=self.rubric_id,
            rubric_version=self.rubric_version,
            output=self.output,
            result_metadata=self.result_metadata,
            result_type=self.result_type,
            value=self.value,
        )


class SQLARubricCentroid(SQLABase):
    __tablename__ = TABLE_RUBRIC_CENTROID

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    collection_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    rubric_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    centroid: Mapped[str] = mapped_column(Text, nullable=False)
    result_type: Mapped[ResultType] = mapped_column(RESULT_TYPE_ENUM, nullable=False)

    # Composite foreign key constraint
    __table_args__ = (
        ForeignKeyConstraint(
            ["rubric_id", "rubric_version"],
            [f"{TABLE_RUBRIC}.id", f"{TABLE_RUBRIC}.version"],
        ),
    )

    # Relationship to rubric
    rubric: Mapped["SQLARubric"] = relationship(
        "SQLARubric",
        back_populates="centroids",
        foreign_keys=[rubric_id, rubric_version],
    )
    # Relationship to judge results through junction table
    judge_result_centroids: Mapped[list["SQLAJudgeResultCentroid"]] = relationship(
        "SQLAJudgeResultCentroid",
        back_populates="centroid",
        cascade="all, delete-orphan",
    )


class SQLAJudgeResultCentroid(SQLABase):
    """Junction table for many-to-many relationship between judge results and centroids."""

    __tablename__ = TABLE_JUDGE_RESULT_CENTROIDS

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    judge_result_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_JUDGE_RESULT}.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    centroid_id: Mapped[str] = mapped_column(
        String(36), ForeignKey(f"{TABLE_RUBRIC_CENTROID}.id"), nullable=False, index=True
    )
    decision: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    result_type: Mapped[ResultType] = mapped_column(RESULT_TYPE_ENUM, nullable=False)

    # Relationships
    judge_result: Mapped["SQLAJudgeResult"] = relationship(
        "SQLAJudgeResult",
        back_populates="centroid_assignments",
    )
    centroid: Mapped["SQLARubricCentroid"] = relationship(
        "SQLARubricCentroid",
        back_populates="judge_result_centroids",
    )

    __table_args__ = (
        UniqueConstraint(
            "judge_result_id",
            "centroid_id",
            name="uq_judge_result_centroid",
        ),
    )


class SQLAJudgeReflection(SQLABase):
    """Stores reflection analysis for multi-rollout judge results."""

    __tablename__ = TABLE_JUDGE_REFLECTION

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_AGENT_RUN}.id", ondelete="CASCADE"),
        nullable=False,
    )
    rubric_id: Mapped[str] = mapped_column(String(36), nullable=False)
    rubric_version: Mapped[int] = mapped_column(Integer, nullable=False)
    judge_result_ids: Mapped[list[str] | None] = mapped_column(ARRAY(String(36)), nullable=True)
    label_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_LABEL}.id", ondelete="CASCADE"),
        nullable=True,
    )
    reflection_output: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    __table_args__ = (
        Index(
            "uq_judge_reflection_with_label",
            "agent_run_id",
            "rubric_id",
            "rubric_version",
            "label_id",
            unique=True,
            postgresql_where=text("label_id IS NOT NULL"),
        ),
        Index(
            "uq_judge_reflection_without_label",
            "agent_run_id",
            "rubric_id",
            "rubric_version",
            unique=True,
            postgresql_where=text("label_id IS NULL"),
        ),
    )

    # Relationship to label
    label: Mapped["SQLALabel | None"] = relationship(
        "SQLALabel",
        foreign_keys=[label_id],
    )
