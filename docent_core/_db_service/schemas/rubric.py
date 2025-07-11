from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent_core._ai_tools.rubric.rubric import JudgeResult, Rubric
from docent_core._db_service.schemas.base import SQLABase
from docent_core._db_service.schemas.tables import TABLE_AGENT_RUN, TABLE_COLLECTION

TABLE_RUBRIC = "rubrics"
TABLE_JUDGE_RESULT = "judge_results"


class SQLARubric(SQLABase):
    __tablename__ = TABLE_RUBRIC

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    high_level_description = mapped_column(Text, nullable=False)
    inclusion_rules = mapped_column(JSONB, nullable=False)
    exclusion_rules = mapped_column(JSONB, nullable=False)

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
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
            collection_id=collection_id,
            high_level_description=rubric.high_level_description,
            inclusion_rules=rubric.inclusion_rules,
            exclusion_rules=rubric.exclusion_rules,
        )

    def to_pydantic(self) -> Rubric:
        return Rubric(
            id=self.id,
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
    rubric_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_RUBRIC}.id"), nullable=False, index=True
    )
    value = mapped_column(Text, nullable=True)

    # Relationship back to rubric
    rubric: Mapped["SQLARubric"] = relationship(
        "SQLARubric",
        back_populates="judge_results",
    )

    @classmethod
    def from_pydantic(cls, judge_result: JudgeResult) -> "SQLAJudgeResult":
        return cls(
            id=judge_result.id,
            agent_run_id=judge_result.agent_run_id,
            rubric_id=judge_result.rubric_id,
            value=judge_result.value,
        )

    def to_pydantic(self) -> JudgeResult:
        return JudgeResult(
            id=self.id,
            agent_run_id=self.agent_run_id,
            rubric_id=self.rubric_id,
            value=self.value,
        )
