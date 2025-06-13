import enum
import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column
from sqlalchemy.schema import UniqueConstraint

from docent._ai_tools.search import SearchResult
from docent._db_service.contexts import ViewContext
from docent._db_service.schemas.auth_models import Permission, User
from docent._db_service.schemas.base import SQLABase
from docent.data_models.agent_run import AgentRun
from docent.data_models.filters import FrameDimension, FrameFilter, Judgment, parse_filter_dict
from docent.data_models.transcript import Transcript

TABLE_FRAME_GRID = "frame_grids"
TABLE_AGENT_RUN = "agent_runs"
TABLE_SEARCH_RESULTS = "search_results"
TABLE_SEARCH_QUERIES = "search_queries"
TABLE_FRAME_DIMENSION = "frame_dimensions"
TABLE_FILTER = "filters"
TABLE_JUDGMENT = "judgments"
TABLE_JOB = "jobs"
TABLE_DIFF_ATTRIBUTE = "diff_attributes"
TABLE_DIFF_CLUSTER = "diff_clusters"
TABLE_TRANSCRIPT = "transcripts"
TABLE_USER = "users"
TABLE_SESSION = "sessions"
TABLE_VIEW = "views"
TABLE_ROLE = "roles"
TABLE_USER_ROLE = "user_roles"
TABLE_ACCESS_CONTROL_ENTRY = "access_control_entries"
TABLE_ORGANIZATION = "organizations"
TABLE_USER_ORGANIZATION = "user_organizations"


def _sanitize_pg_text(text: str) -> str:
    """
    Wow this took almost an hour to debug.
    Postgres rejects strings with \\x00 and \\u0000, but it turns out that
    JSONifying data converts them to the literal characters \\, \\, x, 0, 0.
    """
    return (
        text.translate({0: None})
        .replace("\\\\x00", "")
        .replace("\\\\u0000", "")
        .replace("\\x00", "")
        .replace("\\u0000", "")
    )


class SQLAAgentRun(SQLABase):
    __tablename__ = TABLE_AGENT_RUN

    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    description = mapped_column(Text)

    # Metdata columns as JSONB so they can be keyed into
    # A scan is fine for ~1e4 transcripts; if larger we might want to index
    metadata_json = mapped_column(JSONB, nullable=False)

    # This column is *only* used for regex search; it needs to be preprocessed to remove invalid characters
    text_for_search = mapped_column(Text, nullable=False)

    @classmethod
    def from_agent_run(cls, agent_run: AgentRun, fg_id: str) -> "SQLAAgentRun":
        # Sanitize raw text
        metadata_json = json.loads(_sanitize_pg_text(agent_run.metadata.model_dump_json()))
        text_for_search = _sanitize_pg_text(agent_run.text)

        return cls(
            id=agent_run.id,
            name=agent_run.name,
            description=agent_run.description,
            fg_id=fg_id,
            metadata_json=metadata_json,
            text_for_search=text_for_search,
        )

    def to_agent_run(self, transcripts: dict[str, Transcript]) -> AgentRun:
        return AgentRun(
            id=self.id,
            name=self.name,
            description=self.description,
            metadata=self.metadata_json,
            transcripts=transcripts,
        )


class SQLATranscript(SQLABase):
    __tablename__ = TABLE_TRANSCRIPT

    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    # Key in the transcripts dict in `AgentRun`
    dict_key = mapped_column(Text, nullable=False)

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    description = mapped_column(Text)

    # Core messages data field
    # Content/metadata might contain invalid chars, so store as raw bytes
    messages = mapped_column(LargeBinary, nullable=False)
    metadata_json = mapped_column(LargeBinary, nullable=False)

    @classmethod
    def from_transcript(
        cls, transcript: Transcript, dict_key: str, fg_id: str, agent_run_id: str
    ) -> "SQLATranscript":
        # Serialize to JSON and then convert to bytes to avoid encoding issues
        messages_binary = json.dumps(to_jsonable_python(transcript.messages)).encode("utf-8")
        metadata_binary = json.dumps(to_jsonable_python(transcript.metadata)).encode("utf-8")

        return cls(
            dict_key=dict_key,
            id=transcript.id,
            name=transcript.name,
            description=transcript.description,
            fg_id=fg_id,
            agent_run_id=agent_run_id,
            messages=messages_binary,
            metadata_json=metadata_binary,
        )

    def to_dict_key_and_transcript(self) -> tuple[str, Transcript]:
        messages = json.loads(self.messages.decode("utf-8"))
        metadata = json.loads(self.metadata_json.decode("utf-8"))
        return (
            self.dict_key,
            Transcript(id=self.id, name=self.name, messages=messages, metadata=metadata),
        )


class SQLAFrameGrid(SQLABase):
    __tablename__ = TABLE_FRAME_GRID

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    description = mapped_column(Text)

    # User who created this frame grid
    created_by = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=True, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )


class SQLAFrameDimension(SQLABase):
    __tablename__ = TABLE_FRAME_DIMENSION

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )
    view_id = mapped_column(String(36), ForeignKey(f"{TABLE_VIEW}.id"), nullable=False, index=True)

    # For dimensions that cluster search query results
    search_query = mapped_column(Text, index=True)

    # For metadata dimensions
    metadata_key = mapped_column(Text, index=True)
    maintain_mece = mapped_column(Boolean, index=True)

    # Loading state
    loading_clusters = mapped_column(Boolean, nullable=False)
    loading_marginals = mapped_column(Boolean, nullable=False)

    @classmethod
    def from_frame_dimension(cls, dimension: FrameDimension, ctx: ViewContext):
        """Convert a FrameDimension object to a SQLAFrameDimension object for database storage."""
        sqla_dimension = cls(
            id=dimension.id,
            name=dimension.name,
            fg_id=ctx.fg_id,
            view_id=ctx.view_id,
            search_query=dimension.search_query,
            metadata_key=dimension.metadata_key,
            maintain_mece=dimension.maintain_mece,
            loading_clusters=dimension.loading_clusters,
            loading_marginals=dimension.loading_marginals,
        )

        # Add filters if they exist
        filters: list[SQLAFilter] = []
        if dimension.bins:
            for filter_obj in dimension.bins:
                filters.append(SQLAFilter.from_filter(filter_obj, ctx, dimension.id))

        return sqla_dimension, filters

    def to_frame_dimension(self, filters: list[FrameFilter] | None) -> FrameDimension:
        return FrameDimension(
            id=self.id,
            name=self.name,
            bins=filters,
            search_query=self.search_query,
            metadata_key=self.metadata_key,
            maintain_mece=self.maintain_mece,
            loading_clusters=self.loading_clusters,
            loading_marginals=self.loading_marginals,
        )


class SQLAView(SQLABase):
    __tablename__ = TABLE_VIEW

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    name = mapped_column(Text, nullable=True)
    is_default = mapped_column(Boolean, nullable=False, default=False, index=True)

    base_filter_id = mapped_column(String(36), ForeignKey(f"{TABLE_FILTER}.id"), nullable=True)
    inner_dim_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"), nullable=True
    )
    outer_dim_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"), nullable=True
    )


class SQLAFilter(SQLABase):
    __tablename__ = TABLE_FILTER

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )
    view_id = mapped_column(String(36), ForeignKey(f"{TABLE_VIEW}.id"), nullable=False, index=True)

    # Which dimension the filter "belongs" to (supports the relationships below)
    dimension_id = mapped_column(String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"), index=True)

    # Serialized filter
    filter_json = mapped_column(JSONB, nullable=False)

    # Metadata that we want to index
    filter_type = mapped_column(Text, nullable=False, index=True)
    supports_sql = mapped_column(Boolean, nullable=False, index=True)

    @classmethod
    def from_filter(
        cls,
        filter: FrameFilter,
        ctx: ViewContext,
        dim_id: str | None = None,
    ):
        return cls(
            id=filter.id,
            fg_id=ctx.fg_id,
            view_id=ctx.view_id,
            dimension_id=dim_id,
            filter_json=filter.model_dump(),
            filter_type=filter.type,
            supports_sql=filter.supports_sql,
        )

    def to_filter(self):
        return parse_filter_dict(self.filter_json)


class SQLAJudgment(SQLABase):
    __tablename__ = TABLE_JUDGMENT

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Metadata on the location of the judgment
    filter_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FILTER}.id"), nullable=False, index=True
    )
    agent_run_id = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_AGENT_RUN}.id"),
        nullable=False,
        index=True,
    )
    search_query = mapped_column(Text, index=True)
    search_result_idx = mapped_column(Integer, index=True)

    # The judgment result
    matches = mapped_column(Boolean, nullable=False, index=True)
    reason = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "fg_id",
            "filter_id",
            "agent_run_id",
            "search_query",
            "search_result_idx",
            name="uq_judgment_key_combination",
            # postgresql_nulls_not_distinct=True,
        ),
    )

    @classmethod
    def from_judgment(cls, judgment: Judgment, fg_id: str) -> "SQLAJudgment":
        return cls(
            id=judgment.id,
            fg_id=fg_id,
            agent_run_id=judgment.agent_run_id,
            filter_id=judgment.filter_id,
            search_query=judgment.search_query,
            search_result_idx=judgment.search_result_idx,
            matches=judgment.matches,
            reason=judgment.reason,
        )

    def to_judgment(self) -> Judgment:
        return Judgment(
            id=self.id,
            agent_run_id=self.agent_run_id,
            filter_id=self.filter_id,
            search_query=self.search_query,
            search_result_idx=self.search_result_idx,
            matches=self.matches,
            reason=self.reason,
        )


class SQLASearchResult(SQLABase):
    __tablename__ = TABLE_SEARCH_RESULTS

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Location of the search result
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    search_query = mapped_column(Text, nullable=False, index=True)
    search_result_idx = mapped_column(Integer, index=True)

    # Null indicates no values for this (datapoint, search_query) pair
    # If there are any non-null values, value should never be null
    value = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "fg_id",
            "agent_run_id",
            "search_query",
            "search_result_idx",
            name="uq_search_result_key_combination",
        ),
    )

    @classmethod
    def from_search_result(
        cls,
        search_result: SearchResult,
        fg_id: str,
    ):
        return cls(
            id=search_result.id,
            fg_id=fg_id,
            agent_run_id=search_result.agent_run_id,
            search_query=search_result.search_query,
            search_result_idx=search_result.search_result_idx,
            value=search_result.value,
        )

    def to_search_result(self) -> SearchResult:
        return SearchResult(
            id=self.id,
            agent_run_id=self.agent_run_id,
            search_query=self.search_query,
            search_result_idx=self.search_result_idx,
            value=self.value,
        )


class SQLASearchQuery(SQLABase):
    __tablename__ = TABLE_SEARCH_QUERIES

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    search_query = mapped_column(Text, nullable=False, index=True)

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )


class JobStatus(enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELED = "canceled"
    COMPLETED = "completed"


class SQLAJob(SQLABase):
    __tablename__ = TABLE_JOB

    id = mapped_column(String(36), primary_key=True)
    type = mapped_column(Text)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    job_json = mapped_column(JSONB, nullable=False)
    status = mapped_column(Enum(JobStatus), default=JobStatus.PENDING)


class SQLADiffAttribute(SQLABase):
    __tablename__ = TABLE_DIFF_ATTRIBUTE

    id = mapped_column(String(36), primary_key=True)
    frame_grid_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Location of the diff attribute
    data_id_1 = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    data_id_2 = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    attribute = mapped_column(Text, nullable=False, index=True)
    attribute_idx = mapped_column(Integer, index=True)

    # Null indicates no values for this (data_id_1, data_id_2, attribute) pair
    claim = mapped_column(Text)
    evidence = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "frame_grid_id",
            "data_id_1",
            "data_id_2",
            "attribute",
            "attribute_idx",
            name="uq_diff_attribute_key_combination",
        ),
    )

    @classmethod
    def from_diff_attribute(
        cls,
        data_id_1: str,
        data_id_2: str,
        attribute: str,
        attribute_idx: int | None,
        claim: str | None,
        evidence: str | None,
        fg_id: str,
    ):
        return cls(
            id=str(uuid4()),
            frame_grid_id=fg_id,
            data_id_1=data_id_1,
            data_id_2=data_id_2,
            attribute=attribute,
            attribute_idx=attribute_idx,
            claim=claim,
            evidence=evidence,
        )

    def to_diff_attribute(self):
        from docent._ai_tools.diff import DiffAttribute

        return DiffAttribute(
            id=self.id,
            data_id_1=self.data_id_1,
            data_id_2=self.data_id_2,
            attribute=self.attribute,
            attribute_idx=self.attribute_idx,
            claim=self.claim,
            evidence=self.evidence,
        )


class SQLAUser(SQLABase):
    __tablename__ = TABLE_USER

    id = mapped_column(String(36), primary_key=True)
    email = mapped_column(String(255), nullable=False, unique=True, index=True)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    is_anonymous = mapped_column(Boolean, nullable=False, default=False, index=True)

    @classmethod
    def from_user(cls, user: User) -> "SQLAUser":
        return cls(
            id=user.id,
            email=user.email,
            is_anonymous=user.is_anonymous,
        )

    def to_user(self, organization_ids: list[str]) -> User:
        return User(
            id=self.id,
            email=self.email,
            organization_ids=organization_ids,
            is_anonymous=self.is_anonymous,
        )


class SQLAUserOrganization(SQLABase):
    __tablename__ = TABLE_USER_ORGANIZATION

    user_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), primary_key=True, index=True
    )
    organization_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_ORGANIZATION}.id"), primary_key=True, index=True
    )


class SQLASession(SQLABase):
    __tablename__ = TABLE_SESSION

    id = mapped_column(String(36), primary_key=True)
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    expires_at = mapped_column(DateTime, nullable=False, index=True)
    is_active = mapped_column(Boolean, default=True, nullable=False, index=True)


class SQLAAccessControlEntry(SQLABase):
    __tablename__ = TABLE_ACCESS_CONTROL_ENTRY

    id = mapped_column(String(36), primary_key=True)

    # Who gets the permission: exactly one must be set
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=True, index=True)
    organization_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_ORGANIZATION}.id"), nullable=True, index=True
    )
    is_public = mapped_column(Boolean, nullable=False, default=False, index=True)

    # Which resource the permission is for: exactly one must be set
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=True, index=True
    )
    view_id = mapped_column(String(36), ForeignKey(f"{TABLE_VIEW}.id"), nullable=True, index=True)

    # Permission
    permission = mapped_column(Text, nullable=False, index=True)

    __table_args__ = (
        # Ensure exactly one subject is set
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (organization_id IS NOT NULL)::int + is_public::int = 1",
            name="check_exactly_one_subject",
        ),
        # Ensure exactly one resource is set
        CheckConstraint(
            "(fg_id IS NOT NULL)::int + (view_id IS NOT NULL)::int = 1",
            name="check_exactly_one_resource",
        ),
        # Validate permission values
        # TODO(mengk): figure out how to get SQLA Enum to work; was broken last I tried
        CheckConstraint(
            f"permission IN ({', '.join(repr(p.value) for p in Permission)})",
            name="check_permission_values",
        ),
        # Unique constraint on the combination
        UniqueConstraint(
            "user_id",
            "organization_id",
            "is_public",
            "fg_id",
            "view_id",
            "permission",
            name="uq_access_control_entry_combination",
        ),
    )


class SQLAOrganization(SQLABase):
    __tablename__ = TABLE_ORGANIZATION

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)
    description = mapped_column(Text, nullable=True)
