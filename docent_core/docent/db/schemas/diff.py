from sqlalchemy import (
    Boolean,
    ForeignKey,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.ai_tools.diff.diff import DiffInstance, DiffQuery, DiffResult
from docent_core.docent.ai_tools.diff.propose_claims import DiffClaimsResult
from docent_core.docent.ai_tools.search_paired import (
    ActionResult,
    SearchPairedInstance,
    SearchPairedQuery,
    SearchPairedResult,
)
from docent_core.docent.db.schemas.tables import (
    TABLE_AGENT_RUN,
    TABLE_COLLECTION,
)

TABLE_DIFF_QUERY = "diff_queries"
TABLE_DIFF_RESULT = "diff_results"
TABLE_DIFF_INSTANCE = "diff_instances"
TABLE_DIFF_CLAIMS_RESULT = "diff_claims_results"

TABLE_PAIRED_SEARCH_QUERY = "paired_search_query"
TABLE_PAIRED_SEARCH_RESULT = "paired_search_result"
TABLE_PAIRED_SEARCH_INSTANCE = "paired_search_instance"

#########
# Diffs #
#########


class SQLADiffQuery(SQLABase):
    __tablename__ = TABLE_DIFF_QUERY

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    grouping_md_fields = mapped_column(JSONB, nullable=False)
    md_field_value_1 = mapped_column(JSONB, nullable=False)
    md_field_value_2 = mapped_column(JSONB, nullable=False)
    focus = mapped_column(Text, nullable=True)

    @classmethod
    def from_pydantic(cls, diff_query: DiffQuery, collection_id: str) -> "SQLADiffQuery":
        return cls(
            id=diff_query.id,
            collection_id=collection_id,
            grouping_md_fields=diff_query.grouping_md_fields,
            md_field_value_1=diff_query.md_field_value_1,
            md_field_value_2=diff_query.md_field_value_2,
            focus=diff_query.focus,
        )

    def to_pydantic(self) -> DiffQuery:
        return DiffQuery(
            id=self.id,
            grouping_md_fields=self.grouping_md_fields,
            md_field_value_1=tuple(self.md_field_value_1),
            md_field_value_2=tuple(self.md_field_value_2),
            focus=self.focus,
        )


class SQLADiffResult(SQLABase):
    __tablename__ = TABLE_DIFF_RESULT

    id = mapped_column(String(36), primary_key=True)
    diff_query_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_DIFF_QUERY}.id"), nullable=False, index=True
    )

    agent_run_1_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    agent_run_2_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )

    instances: Mapped[list["SQLADiffInstance"]] = relationship(
        "SQLADiffInstance",
        back_populates="result",
        cascade="all, delete-orphan",
    )

    @classmethod
    def from_pydantic(cls, diff_result: DiffResult, query_id: str) -> "SQLADiffResult":
        sqla_instances = (
            [
                SQLADiffInstance.from_pydantic(instance, diff_result.id)
                for instance in diff_result.instances
            ]
            if diff_result.instances is not None
            else []
        )
        return cls(
            id=diff_result.id,
            diff_query_id=query_id,
            agent_run_1_id=diff_result.agent_run_1_id,
            agent_run_2_id=diff_result.agent_run_2_id,
            instances=sqla_instances,
        )

    def to_pydantic(self) -> DiffResult:
        return DiffResult(
            id=self.id,
            agent_run_1_id=self.agent_run_1_id,
            agent_run_2_id=self.agent_run_2_id,
            instances=[instance.to_pydantic() for instance in self.instances],
        )


class SQLADiffInstance(SQLABase):
    __tablename__ = TABLE_DIFF_INSTANCE

    id = mapped_column(String(36), primary_key=True)
    paired_diff_result_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_DIFF_RESULT}.id"), nullable=False, index=True
    )

    summary = mapped_column(Text, nullable=False)
    shared_context = mapped_column(Text, nullable=False)
    agent_1_action = mapped_column(Text, nullable=False)
    agent_1_evidence = mapped_column(JSONB, nullable=False)
    agent_2_action = mapped_column(Text, nullable=False)
    agent_2_evidence = mapped_column(JSONB, nullable=False)

    result: Mapped["SQLADiffResult"] = relationship(
        "SQLADiffResult",
        back_populates="instances",
    )

    @classmethod
    def from_pydantic(
        cls, diff_instance: DiffInstance, paired_diff_result_id: str
    ) -> "SQLADiffInstance":
        return cls(
            id=diff_instance.id,
            paired_diff_result_id=paired_diff_result_id,
            summary=diff_instance.summary,
            shared_context=diff_instance.shared_context,
            agent_1_action=diff_instance.agent_1_action,
            agent_1_evidence=diff_instance.agent_1_evidence,
            agent_2_action=diff_instance.agent_2_action,
            agent_2_evidence=diff_instance.agent_2_evidence,
        )

    def to_pydantic(self) -> DiffInstance:
        return DiffInstance(
            id=self.id,
            summary=self.summary,
            shared_context=self.shared_context,
            agent_1_action=self.agent_1_action,
            agent_1_evidence=self.agent_1_evidence,
            agent_2_action=self.agent_2_action,
            agent_2_evidence=self.agent_2_evidence,
        )


class SQLADiffClaimsResult(SQLABase):
    __tablename__ = TABLE_DIFF_CLAIMS_RESULT

    id = mapped_column(String(36), primary_key=True)
    diff_query_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_DIFF_QUERY}.id"), nullable=False, index=True
    )

    paired_search_queries: Mapped[list["SQLAPairedSearchQuery"]] = relationship(
        "SQLAPairedSearchQuery",
        back_populates="diff_claims_result",
        cascade="all, delete-orphan",
    )

    @classmethod
    def from_pydantic(
        cls, claims_result: DiffClaimsResult, diff_query_id: str, collection_id: str
    ) -> "SQLADiffClaimsResult":
        sqla_paired_search_queries = [
            SQLAPairedSearchQuery.from_pydantic(query, collection_id)
            for query in claims_result.instances
        ]
        return cls(
            id=claims_result.id,
            diff_query_id=diff_query_id,
            paired_search_queries=sqla_paired_search_queries,
        )

    def to_pydantic(self) -> DiffClaimsResult:
        return DiffClaimsResult(
            id=self.id,
            diff_query_id=self.diff_query_id,
            instances=[query.to_pydantic() for query in self.paired_search_queries],
        )


#################
# Paired Search #
#################


class SQLAPairedSearchQuery(SQLABase):
    __tablename__ = TABLE_PAIRED_SEARCH_QUERY

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    # Nullable because you can search without having it tied to a claims result
    diff_claims_result_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_DIFF_CLAIMS_RESULT}.id"), nullable=True, index=True
    )

    grouping_md_fields = mapped_column(JSONB, nullable=False)
    md_field_value_1 = mapped_column(JSONB, nullable=False)
    md_field_value_2 = mapped_column(JSONB, nullable=False)

    context = mapped_column(Text, nullable=False)
    action_1 = mapped_column(Text, nullable=False)
    action_2 = mapped_column(Text, nullable=False)

    diff_claims_result: Mapped["SQLADiffClaimsResult"] = relationship(
        "SQLADiffClaimsResult",
        back_populates="paired_search_queries",
    )

    results: Mapped[list["SQLAPairedSearchResult"]] = relationship(
        "SQLAPairedSearchResult",
        back_populates="query",
        cascade="all, delete-orphan",
    )

    @classmethod
    def from_pydantic(
        cls,
        paired_search_query: SearchPairedQuery,
        collection_id: str,
    ) -> "SQLAPairedSearchQuery":
        return cls(
            id=paired_search_query.id,
            collection_id=collection_id,
            grouping_md_fields=paired_search_query.grouping_md_fields,
            md_field_value_1=paired_search_query.md_field_value_1,
            md_field_value_2=paired_search_query.md_field_value_2,
            context=paired_search_query.context,
            action_1=paired_search_query.action_1,
            action_2=paired_search_query.action_2,
        )

    def to_pydantic(self) -> SearchPairedQuery:
        return SearchPairedQuery(
            id=self.id,
            grouping_md_fields=self.grouping_md_fields,
            md_field_value_1=tuple(self.md_field_value_1),
            md_field_value_2=tuple(self.md_field_value_2),
            context=self.context,
            action_1=self.action_1,
            action_2=self.action_2,
        )


class SQLAPairedSearchResult(SQLABase):
    __tablename__ = TABLE_PAIRED_SEARCH_RESULT

    id = mapped_column(String(36), primary_key=True)
    paired_search_query_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_PAIRED_SEARCH_QUERY}.id"), nullable=False, index=True
    )

    agent_run_1_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    agent_run_2_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )

    # Add the missing back-reference
    query: Mapped["SQLAPairedSearchQuery"] = relationship(
        "SQLAPairedSearchQuery",
        back_populates="results",
    )

    instances: Mapped[list["SQLAPairedSearchInstance"]] = relationship(
        "SQLAPairedSearchInstance",
        back_populates="result",
        cascade="all, delete-orphan",
    )

    def to_pydantic(self) -> SearchPairedResult:
        """
        Note: `self.instances` must have already been loaded, otherwise this function will error.
        Use `.options(selectinload(...))` to load them explicitly.
        """
        return SearchPairedResult(
            id=self.id,
            agent_run_1_id=self.agent_run_1_id,
            agent_run_2_id=self.agent_run_2_id,
            instances=[instance.to_pydantic() for instance in self.instances],
        )

    @classmethod
    def from_pydantic(cls, paired_search_result: SearchPairedResult, query_id: str):
        sqla_instances = (
            [
                SQLAPairedSearchInstance.from_pydantic(instance, paired_search_result.id)
                for instance in paired_search_result.instances
            ]
            if paired_search_result.instances is not None
            else []
        )
        return cls(
            id=paired_search_result.id,
            paired_search_query_id=query_id,
            agent_run_1_id=paired_search_result.agent_run_1_id,
            agent_run_2_id=paired_search_result.agent_run_2_id,
            instances=sqla_instances,
        )


class SQLAPairedSearchInstance(SQLABase):
    __tablename__ = TABLE_PAIRED_SEARCH_INSTANCE

    id = mapped_column(String(36), primary_key=True)
    paired_search_result_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_PAIRED_SEARCH_RESULT}.id"), nullable=False, index=True
    )

    shared_context = mapped_column(Text, nullable=False)
    # 11
    agent_1_action_1 = mapped_column(Boolean, nullable=False)
    agent_1_action_1_explanation = mapped_column(Text, nullable=True)
    # 12
    agent_1_action_2 = mapped_column(Boolean, nullable=False)
    agent_1_action_2_explanation = mapped_column(Text, nullable=True)
    # 21
    agent_2_action_1 = mapped_column(Boolean, nullable=False)
    agent_2_action_1_explanation = mapped_column(Text, nullable=True)
    # 22
    agent_2_action_2 = mapped_column(Boolean, nullable=False)
    agent_2_action_2_explanation = mapped_column(Text, nullable=True)

    result: Mapped["SQLAPairedSearchResult"] = relationship(
        "SQLAPairedSearchResult",
        back_populates="instances",
    )

    @classmethod
    def from_pydantic(
        cls, paired_search_instance: SearchPairedInstance, result_id: str
    ) -> "SQLAPairedSearchInstance":
        return cls(
            id=paired_search_instance.id,
            paired_search_result_id=result_id,
            shared_context=paired_search_instance.shared_context,
            # 11
            agent_1_action_1=paired_search_instance.agent_1_action_1.performed,
            agent_1_action_1_explanation=paired_search_instance.agent_1_action_1.explanation,
            # 12
            agent_1_action_2=paired_search_instance.agent_1_action_2.performed,
            agent_1_action_2_explanation=paired_search_instance.agent_1_action_2.explanation,
            # 21
            agent_2_action_1=paired_search_instance.agent_2_action_1.performed,
            agent_2_action_1_explanation=paired_search_instance.agent_2_action_1.explanation,
            # 22
            agent_2_action_2=paired_search_instance.agent_2_action_2.performed,
            agent_2_action_2_explanation=paired_search_instance.agent_2_action_2.explanation,
        )

    def to_pydantic(self) -> SearchPairedInstance:
        return SearchPairedInstance(
            id=self.id,
            shared_context=self.shared_context,
            agent_1_action_1=ActionResult(
                performed=self.agent_1_action_1,
                explanation=self.agent_1_action_1_explanation,
            ),
            agent_1_action_2=ActionResult(
                performed=self.agent_1_action_2,
                explanation=self.agent_1_action_2_explanation,
            ),
            agent_2_action_1=ActionResult(
                performed=self.agent_2_action_1,
                explanation=self.agent_2_action_1_explanation,
            ),
            agent_2_action_2=ActionResult(
                performed=self.agent_2_action_2,
                explanation=self.agent_2_action_2_explanation,
            ),
        )
