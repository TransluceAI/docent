from typing import Optional

from pydantic import BaseModel
from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent.data_models.citation import parse_citations_multi_run
from docent.data_models.shared_types import EvidenceWithCitation
from docent_core._db_service.contexts import ViewContext
from docent_core._db_service.schemas.tables import TABLE_AGENT_RUN, TABLE_COLLECTION, SQLABase


class MessageState:
    """Represents the state of a message in a transcript, including its action, goal, and context."""

    def __init__(self, message_idx: int, action: str, goal: str, past_actions: str):
        self.message_idx = message_idx
        self.action = action
        self.goal = goal
        self.past_actions = past_actions

    def __str__(self):
        return f"[B{self.message_idx}]\nAction: {self.action}\nGoal: {self.goal}\nRelevant past actions: {self.past_actions}"


class DiffTheme(BaseModel):
    """A single theme of differences between two agent runs."""

    name: str
    description: str
    claim_ids: list[str]


class Claim(BaseModel):
    """A single claim about the difference between two agent runs."""

    id: str
    idx: int
    claim_summary: str
    shared_context: Optional[str] = None
    agent_1_action: str
    agent_2_action: str
    evidence: str
    evidence_with_citations: Optional[EvidenceWithCitation] = None


class TranscriptDiff(BaseModel):
    """Represents the differences between two agent run transcripts."""

    id: str
    diffs_report_id: str
    agent_run_1_id: str
    agent_run_2_id: str
    title: str
    claims: list[Claim]


class DiffsReport(BaseModel):
    id: str
    name: str
    experiment_id_1: str
    experiment_id_2: str
    diffs: list[TranscriptDiff]


TABLE_TRANSCRIPT_DIFF = "transcript_diff"
TABLE_DIFFS_REPORT = "diffs_report"


class SQLATranscriptDiff(SQLABase):
    __tablename__ = TABLE_TRANSCRIPT_DIFF

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    diffs_report_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_DIFFS_REPORT}.id"), nullable=False, index=True
    )

    # Location of the diff attribute
    agent_run_1_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    agent_run_2_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    title = mapped_column(Text, nullable=False, index=True)

    # Relationship to claims with cascade delete
    claims: Mapped[list["SQLAClaim"]] = relationship(
        "SQLAClaim",
        back_populates="transcript_diff",
        cascade="all, delete-orphan",
        lazy="selectin",  # Eager load claims when diff is loaded
    )

    # Add relationship back to diffs_report
    diffs_report = relationship("SQLADiffsReport", back_populates="diffs")

    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "diffs_report_id",
            "agent_run_1_id",
            "agent_run_2_id",
            name="uq_transcript_diff_key_combination",
        ),
    )

    @classmethod
    def from_pydantic(cls, pydantic_obj: TranscriptDiff, ctx: ViewContext) -> "SQLATranscriptDiff":
        claims = [SQLAClaim.from_pydantic(claim) for claim in pydantic_obj.claims]
        return cls(
            id=pydantic_obj.id,
            title=pydantic_obj.title,
            collection_id=ctx.collection_id,
            agent_run_1_id=pydantic_obj.agent_run_1_id,
            agent_run_2_id=pydantic_obj.agent_run_2_id,
            claims=claims,
        )

    def to_pydantic(self) -> TranscriptDiff:
        return TranscriptDiff(
            id=self.id,
            diffs_report_id=self.diffs_report_id,
            title=self.title,
            agent_run_1_id=self.agent_run_1_id,
            agent_run_2_id=self.agent_run_2_id,
            claims=[claim.to_pydantic() for claim in self.claims],
        )


class SQLAClaim(SQLABase):
    __tablename__ = "claim"

    id = mapped_column(String(36), primary_key=True)
    transcript_diff_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_TRANSCRIPT_DIFF}.id"), nullable=False, index=True
    )
    idx = mapped_column(Integer, nullable=False, index=True)
    claim_summary = mapped_column(Text, nullable=False)
    shared_context = mapped_column(Text, nullable=True)
    agent_1_action = mapped_column(Text, nullable=False)
    agent_2_action = mapped_column(Text, nullable=False)
    evidence = mapped_column(Text, nullable=False)

    # Relationship to parent diff
    transcript_diff = relationship("SQLATranscriptDiff", back_populates="claims", lazy="selectin")

    @classmethod
    def from_pydantic(cls, pydantic_obj: Claim) -> "SQLAClaim":
        return cls(
            id=pydantic_obj.id,
            idx=pydantic_obj.idx,
            claim_summary=pydantic_obj.claim_summary,
            shared_context=pydantic_obj.shared_context,
            agent_1_action=pydantic_obj.agent_1_action,
            agent_2_action=pydantic_obj.agent_2_action,
            evidence=pydantic_obj.evidence,
        )

    def to_pydantic(self) -> Claim:
        return Claim(
            id=self.id,
            idx=self.idx,
            claim_summary=self.claim_summary,
            shared_context=self.shared_context,
            agent_1_action=self.agent_1_action,
            agent_2_action=self.agent_2_action,
            evidence=self.evidence,
            evidence_with_citations=EvidenceWithCitation(
                evidence=self.evidence, citations=parse_citations_multi_run(self.evidence)
            ),
        )


class SQLADiffsReport(SQLABase):
    __tablename__ = TABLE_DIFFS_REPORT

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    name = mapped_column(Text, nullable=False)
    # TODO - would be great to foreign key these somehow
    experiment_id_1 = mapped_column(String(36), nullable=False)
    experiment_id_2 = mapped_column(String(36), nullable=False)
    diffs: Mapped[list["SQLATranscriptDiff"]] = relationship(
        "SQLATranscriptDiff",
        back_populates="diffs_report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def to_pydantic(self) -> DiffsReport:
        return DiffsReport(
            id=self.id,
            name=self.name,
            experiment_id_1=self.experiment_id_1,
            experiment_id_2=self.experiment_id_2,
            diffs=[diff.to_pydantic() for diff in self.diffs],
        )
