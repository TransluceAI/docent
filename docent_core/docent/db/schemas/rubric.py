from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent_core._ai_tools.rubric.rubric import JudgeResult, ResultType, Rubric
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.schemas.tables import TABLE_AGENT_RUN, TABLE_COLLECTION

TABLE_RUBRIC = "rubrics"
TABLE_JUDGE_RESULT = "judge_results"
TABLE_RUBRIC_CENTROID = "rubric_centroids"
TABLE_JUDGE_RESULT_CENTROIDS = "judge_result_centroids"


class SQLARubric(SQLABase):
    __tablename__ = TABLE_RUBRIC

    id = mapped_column(String(36), nullable=False)
    version = mapped_column(Integer, nullable=False, default=1)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    high_level_description = mapped_column(Text, nullable=False)
    inclusion_rules = mapped_column(JSONB, nullable=False)
    exclusion_rules = mapped_column(JSONB, nullable=False)

    created_at = mapped_column(
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

    @classmethod
    def from_pydantic(cls, rubric: Rubric, collection_id: str) -> "SQLARubric":
        return cls(
            id=rubric.id,
            version=rubric.version,
            collection_id=collection_id,
            high_level_description=rubric.high_level_description,
            inclusion_rules=rubric.inclusion_rules,
            exclusion_rules=rubric.exclusion_rules,
        )

    def to_pydantic(self) -> Rubric:
        return Rubric(
            id=self.id,
            version=self.version,
            high_level_description=self.high_level_description,
            inclusion_rules=self.inclusion_rules,
            exclusion_rules=self.exclusion_rules,
        )


class SQLAJudgeResult(SQLABase):
    __tablename__ = TABLE_JUDGE_RESULT

    id = mapped_column(String(36), primary_key=True)
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    rubric_id = mapped_column(String(36), nullable=False, index=True)
    rubric_version = mapped_column(Integer, nullable=False, index=True)
    value = mapped_column(Text, nullable=True)
    result_type = mapped_column(Enum(ResultType), nullable=False)

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
            value=judge_result.value,
            result_type=judge_result.result_type,
        )

    def to_pydantic(self) -> JudgeResult:
        return JudgeResult(
            id=self.id,
            agent_run_id=self.agent_run_id,
            rubric_id=self.rubric_id,
            rubric_version=self.rubric_version,
            value=self.value,
            result_type=self.result_type,
        )


class SQLARubricCentroid(SQLABase):
    __tablename__ = TABLE_RUBRIC_CENTROID

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    rubric_id = mapped_column(String(36), nullable=False, index=True)
    rubric_version = mapped_column(Integer, nullable=False, index=True)
    centroid: Mapped[str] = mapped_column(Text, nullable=False)
    result_type = mapped_column(Enum(ResultType), nullable=False)

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

    id = mapped_column(String(36), primary_key=True)
    judge_result_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_JUDGE_RESULT}.id"), nullable=False, index=True
    )
    centroid_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_RUBRIC_CENTROID}.id"), nullable=False, index=True
    )
    decision = mapped_column(Boolean, nullable=False)
    reason = mapped_column(Text, nullable=False)
    result_type = mapped_column(Enum(ResultType), nullable=False)

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
