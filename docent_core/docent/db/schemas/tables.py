import enum
import json
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from pydantic_core import to_jsonable_python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.schema import UniqueConstraint

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.transcript import Transcript, TranscriptGroup, fake_model_dump
from docent_core._ai_tools.search import SearchResult
from docent_core._db_service.schemas.base import SQLABase
from docent_core.docent.db.filters import ComplexFilter, parse_filter_dict
from docent_core.docent.db.schemas.auth_models import Organization, Permission, User

logger = get_logger(__name__)

TABLE_COLLECTION = "collections"
TABLE_AGENT_RUN = "agent_runs"
TABLE_TRANSCRIPT_EMBEDDING = "transcript_embeddings"
EMBEDDING_DIM = 512
TABLE_SEARCH_RESULTS = "search_results"
TABLE_SEARCH_QUERIES = "search_queries"
TABLE_FILTER = "filters"
TABLE_JUDGMENT = "judgments"
TABLE_JOB = "jobs"
TABLE_TRANSCRIPT = "transcripts"
TABLE_TRANSCRIPT_GROUP = "transcript_groups"
TABLE_USER = "users"
TABLE_SESSION = "sessions"
TABLE_VIEW = "views"
TABLE_ROLE = "roles"
TABLE_USER_ROLE = "user_roles"
TABLE_ACCESS_CONTROL_ENTRY = "access_control_entries"
TABLE_ORGANIZATION = "organizations"
TABLE_USER_ORGANIZATION = "user_organizations"
TABLE_SEARCH_CLUSTER = "search_clusters"
TABLE_SEARCH_RESULT_CLUSTER = "search_result_clusters"
TABLE_ANALYTICS_EVENT = "analytics_events"
TABLE_CHAT_SESSION = "chat_sessions"
TABLE_API_KEY = "api_keys"
TABLE_TELEMETRY_LOG = "telemetry_logs"


def sanitize_pg_text(text: str) -> str:
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

    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    description = mapped_column(Text)

    # Metdata columns as JSONB so they can be keyed into
    # A scan is fine for ~1e4 transcripts; if larger we might want to index
    metadata_json = mapped_column(JSONB, nullable=False)

    # This column is *only* used for regex search; it needs to be preprocessed to remove invalid characters
    text_for_search = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_agent_runs_metadata_json_gin", "metadata_json", postgresql_using="gin"),
    )

    @classmethod
    def from_agent_run(cls, agent_run: AgentRun, collection_id: str) -> "SQLAAgentRun":
        # Sanitize raw text
        metadata_json = json.loads(
            sanitize_pg_text(json.dumps(fake_model_dump(agent_run.metadata)))
        )
        text_for_search = sanitize_pg_text(agent_run.text)
        return cls(
            id=agent_run.id,
            name=agent_run.name,
            description=agent_run.description,
            collection_id=collection_id,
            metadata_json=metadata_json,
            text_for_search=text_for_search,
        )

    def to_agent_run(self, transcripts: dict[str, Transcript]) -> AgentRun:
        metadata = self.metadata_json
        assert isinstance(metadata, dict), f"metadata is not a dict: {metadata}"

        return AgentRun(
            id=self.id,
            name=self.name,
            description=self.description,
            metadata=cast(dict[str, Any], metadata),
            transcripts=transcripts,
        )


class SQLATranscript(SQLABase):
    __tablename__ = TABLE_TRANSCRIPT

    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    # Key in the transcripts dict in `AgentRun`
    dict_key = mapped_column(Text, nullable=False)

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=True)
    description = mapped_column(Text, nullable=True)
    transcript_group_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_TRANSCRIPT_GROUP}.id"), nullable=True, index=True
    )

    # Core messages data field
    # Content/metadata might contain invalid chars, so store as raw bytes
    messages = mapped_column(LargeBinary, nullable=False)
    metadata_json = mapped_column(LargeBinary, nullable=False)

    @classmethod
    def from_transcript(
        cls, transcript: Transcript, dict_key: str, collection_id: str, agent_run_id: str
    ) -> "SQLATranscript":
        # Serialize to JSON and then convert to bytes to avoid encoding issues
        messages_binary = json.dumps(to_jsonable_python(transcript.messages)).encode("utf-8")
        metadata_binary = json.dumps(fake_model_dump(transcript.metadata)).encode("utf-8")

        return cls(
            dict_key=dict_key,
            id=transcript.id,
            name=transcript.name,
            description=transcript.description,
            transcript_group_id=transcript.transcript_group_id,
            collection_id=collection_id,
            agent_run_id=agent_run_id,
            messages=messages_binary,
            metadata_json=metadata_binary,
        )

    def to_dict_key_and_transcript(self) -> tuple[str, Transcript]:
        messages = json.loads(self.messages.decode("utf-8"))
        metadata = json.loads(self.metadata_json)  # TODO(vincent): fix this .decode("utf-8")
        assert isinstance(metadata, dict), f"metadata is not a dict: {metadata}"
        return (
            self.dict_key,
            Transcript(
                id=self.id,
                name=self.name,
                description=self.description,
                transcript_group_id=self.transcript_group_id,
                messages=messages,
                metadata=cast(dict[str, Any], metadata),
            ),
        )


class SQLATranscriptGroup(SQLABase):
    __tablename__ = TABLE_TRANSCRIPT_GROUP

    id = mapped_column(String(36), primary_key=True)

    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    name = mapped_column(Text, nullable=True)
    description = mapped_column(Text, nullable=True)
    parent_transcript_group_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_TRANSCRIPT_GROUP}.id"), nullable=True, index=True
    )

    # Core metadata data field
    metadata_json = mapped_column(JSONB, nullable=False)

    @classmethod
    def from_transcript_group(
        cls, transcript_group: TranscriptGroup, collection_id: str
    ) -> "SQLATranscriptGroup":
        # Convert metadata to JSON-serializable dict for JSONB column
        metadata_json = to_jsonable_python(transcript_group.metadata)

        return cls(
            id=transcript_group.id,
            name=transcript_group.name,
            description=transcript_group.description,
            parent_transcript_group_id=transcript_group.parent_transcript_group_id,
            collection_id=collection_id,
            metadata_json=metadata_json,
        )

    def to_transcript_group(self) -> TranscriptGroup:
        return TranscriptGroup(
            id=self.id,
            name=self.name,
            description=self.description,
            parent_transcript_group_id=self.parent_transcript_group_id,
            metadata=self.metadata_json,
        )


class SQLATranscriptEmbedding(SQLABase):
    __tablename__ = TABLE_TRANSCRIPT_EMBEDDING

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=False)


class SQLACollection(SQLABase):
    __tablename__ = TABLE_COLLECTION

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    description = mapped_column(Text)

    # User who created this collection
    created_by = mapped_column(
        String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True
    )

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    views: Mapped[list["SQLAView"]] = relationship(
        "SQLAView",
        back_populates="collection",
        cascade="all, delete-orphan",
    )


class SQLAView(SQLABase):
    __tablename__ = TABLE_VIEW

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    # Owner of this view. Combined with collection_id must be unique (for non-sharing rows).
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True)
    name = mapped_column(Text, nullable=True)

    base_filter_dict = mapped_column(JSONB, nullable=True)
    # These keys reference metadata fields
    # TODO(mengk,gregor): can we get explicit FK relations?
    inner_bin_key = mapped_column(Text, nullable=True)
    outer_bin_key = mapped_column(Text, nullable=True)

    for_sharing = mapped_column(Boolean, nullable=False, default=False)

    user: Mapped["SQLAUser"] = relationship("SQLAUser", lazy="select")
    collection: Mapped["SQLACollection"] = relationship(
        "SQLACollection",
        back_populates="views",
    )

    acl_entries: Mapped[list["SQLAAccessControlEntry"]] = relationship(
        "SQLAAccessControlEntry",
        back_populates="view",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # Enforce that the combination of collection_id and user_id is unique for non-sharing views
    __table_args__ = (
        Index(
            "idx_view_collection_user_unique_non_sharing",
            "collection_id",
            "user_id",
            unique=True,
            postgresql_where="for_sharing = false",
        ),
    )

    @property
    def base_filter(self) -> ComplexFilter | None:
        if self.base_filter_dict is None:
            return None
        result = parse_filter_dict(deepcopy(self.base_filter_dict))
        assert isinstance(result, ComplexFilter)
        return result


class SQLASearchCluster(SQLABase):
    __tablename__ = TABLE_SEARCH_CLUSTER

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )
    centroid = mapped_column(Text, nullable=False)
    search_query_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_SEARCH_QUERIES}.id"), nullable=True, index=True
    )
    search_query = mapped_column(Text, nullable=True)  # bwd compat

    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Relationship to search results through junction table
    search_result_clusters = relationship("SQLASearchResultCluster", back_populates="cluster")


class SQLASearchResultCluster(SQLABase):
    """Junction table for many-to-many relationship between search results and clusters."""

    __tablename__ = TABLE_SEARCH_RESULT_CLUSTER

    id = mapped_column(String(36), primary_key=True)
    search_result_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_SEARCH_RESULTS}.id"), nullable=False, index=True
    )
    cluster_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_SEARCH_CLUSTER}.id"), nullable=False, index=True
    )
    decision = mapped_column(Boolean, nullable=False)
    reason = mapped_column(Text, nullable=False)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )

    # Relationships
    search_result = relationship("SQLASearchResult", back_populates="cluster_assignments")
    cluster = relationship("SQLASearchCluster", back_populates="search_result_clusters")

    __table_args__ = (
        UniqueConstraint(
            "search_result_id",
            "cluster_id",
            name="uq_search_result_cluster",
        ),
    )


class SQLASearchResult(SQLABase):
    __tablename__ = TABLE_SEARCH_RESULTS

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
    )

    # Location of the search result
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    search_query_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_SEARCH_QUERIES}.id"), nullable=True, index=True
    )
    search_query = mapped_column(Text, nullable=True)  # bwd compat
    search_result_idx = mapped_column(Integer, index=True)

    # Null indicates no values for this (datapoint, search_query) pair
    # If there are any non-null values, value should never be null
    value = mapped_column(Text)

    # Relationship to clusters through junction table
    cluster_assignments = relationship("SQLASearchResultCluster", back_populates="search_result")

    __table_args__ = (
        UniqueConstraint(
            "collection_id",
            "agent_run_id",
            "search_query_id",
            "search_result_idx",
            name="uq_search_result_key_combination",
        ),
    )

    @classmethod
    def from_search_result(
        cls,
        search_result: SearchResult,
        collection_id: str,
    ):
        value = search_result.value
        if value is not None:
            value = sanitize_pg_text(value)
        return cls(
            id=search_result.id,
            collection_id=collection_id,
            agent_run_id=search_result.agent_run_id,
            search_query_id=search_result.search_query_id,
            search_result_idx=search_result.search_result_idx,
            value=value,
        )

    def to_search_result(self) -> SearchResult:
        return SearchResult(
            id=self.id,
            agent_run_id=self.agent_run_id,
            search_query_id=self.search_query_id,
            search_result_idx=self.search_result_idx,
            value=self.value,
        )


class SQLASearchQuery(SQLABase):
    __tablename__ = TABLE_SEARCH_QUERIES

    id = mapped_column(String(36), primary_key=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=False, index=True
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


class SQLAUser(SQLABase):
    __tablename__ = TABLE_USER

    id = mapped_column(String(36), primary_key=True)
    email = mapped_column(String(255), nullable=False, unique=True, index=True)
    password_hash = mapped_column(String(255), nullable=False)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    is_anonymous = mapped_column(Boolean, nullable=False, default=False, index=True)

    organizations: Mapped[list["SQLAOrganization"]] = relationship(
        "SQLAOrganization",
        secondary=TABLE_USER_ORGANIZATION,
        back_populates="users",
        lazy="selectin",
    )

    @classmethod
    def from_user(cls, user: User) -> "SQLAUser":
        return cls(
            id=user.id,
            email=user.email,
            is_anonymous=user.is_anonymous,
        )

    def to_user(self) -> User:
        return User(
            id=self.id,
            email=self.email,
            organization_ids=[org.id for org in self.organizations],
            is_anonymous=self.is_anonymous,
        )


class SQLAOrganization(SQLABase):
    __tablename__ = TABLE_ORGANIZATION

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text, nullable=False)
    description = mapped_column(Text, nullable=True)

    users: Mapped[list["SQLAUser"]] = relationship(
        "SQLAUser",
        secondary=TABLE_USER_ORGANIZATION,
        back_populates="organizations",
    )

    def to_organization(self) -> Organization:
        return Organization(
            id=self.id,
            name=self.name,
            description=self.description,
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
    collection_id = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_COLLECTION}.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    view_id = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_VIEW}.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # Permission
    permission = mapped_column(Text, nullable=False, index=True)
    user: Mapped["SQLAUser"] = relationship("SQLAUser", backref="access_control_entries")
    organization: Mapped["SQLAOrganization"] = relationship(
        "SQLAOrganization", backref="access_control_entries"
    )
    view: Mapped["SQLAView"] = relationship("SQLAView", back_populates="acl_entries")

    def __repr__(self):
        return f"SQLAAccessControlEntry(id={self.id}, subject={self.subject()}, permission={self.permission})"

    def subject(self) -> SQLAUser | SQLAOrganization | Literal["public"]:
        return self.user or self.organization or "public"

    __table_args__ = (
        # Ensure exactly one subject is set
        CheckConstraint(
            "(user_id IS NOT NULL)::int + (organization_id IS NOT NULL)::int + is_public::int = 1",
            name="check_exactly_one_subject",
        ),
        # Ensure exactly one resource is set
        CheckConstraint(
            "(collection_id IS NOT NULL)::int + (view_id IS NOT NULL)::int = 1",
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
            "collection_id",
            "view_id",
            "permission",
            name="uq_access_control_entry_combination",
        ),
    )


class EndpointType(enum.Enum):
    """Enum for tracking which router endpoints are being called."""

    SIGNUP = "signup"
    CREATE_ANONYMOUS_SESSION = "create_anonymous_session"
    CREATE_FG = "create_collection"
    GET_AGENT_RUN = "get_agent_run"
    POST_AGENT_RUNS = "post_agent_runs"
    JOIN = "join"
    POST_BASE_FILTER = "post_base_filter"
    CLONE_OWN_VIEW = "clone_own_view"
    APPLY_EXISTING_VIEW = "apply_existing_view"
    GET_EXISTING_SEARCH_RESULTS = "get_existing_search_results"
    GET_REGEX_SNIPPETS_ENDPOINT = "get_regex_snippets_endpoint"
    UPSERT_COLLABORATOR = "upsert_collaborator"
    DELETE_FILTER = "delete_filter"
    POST_FILTER = "post_filter"
    START_COMPUTE_SEARCH = "start_compute_search"
    RESUME_COMPUTE_SEARCH = "resume_compute_search"
    GET_EXISTING_CLUSTERS = "get_existing_clusters"
    START_CLUSTER_SEARCH_RESULTS = "start_cluster_search_results"
    GET_TA_MESSAGE = "get_ta_message"
    GET_DIFFS_REPORT = "get_diffs_report"
    START_COMPUTE_DIFFS = "start_compute_diffs"
    COMPUTE_DIFF_CLUSTERS = "compute_diff_clusters"
    GET_TRANSCRIPT_DIFF = "get_transcript_diff"
    CREATE_CHART = "create_chart"
    UPDATE_CHART = "update_chart"
    DELETE_CHART = "delete_chart"
    MAKE_COLLECTION_PUBLIC = "make_collection_public"
    SHARE_COLLECTION_WITH_EMAIL = "share_collection_with_email"


class SQLAChatSession(SQLABase):
    __tablename__ = TABLE_CHAT_SESSION

    id = mapped_column(String(36), primary_key=True)
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True)

    # JSON field to store all messages
    messages = mapped_column(JSONB, nullable=False, default=list)

    # Associated agent run IDs for context
    agent_run_ids = mapped_column(JSONB, nullable=False, default=list)

    updated_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False, index=True
    )

    user: Mapped["SQLAUser"] = relationship("SQLAUser", lazy="select")


class SQLAAnalyticsEvent(SQLABase):
    __tablename__ = TABLE_ANALYTICS_EVENT

    id = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))

    # The collection ID (can be None for endpoints that don't operate on a specific collection)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=True, index=True
    )

    # The user ID (can be None for anonymous users)
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=True, index=True)

    # The endpoint that was called
    endpoint = mapped_column(Enum(EndpointType), nullable=False, index=True)

    # When the endpoint was called
    called_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False, index=True
    )

    @classmethod
    def create_event(
        cls,
        endpoint: EndpointType,
        collection_id: str | None = None,
        user_id: str | None = None,
    ) -> "SQLAAnalyticsEvent":
        """Create a new analytics event."""
        return cls(
            endpoint=endpoint,
            collection_id=collection_id,
            user_id=user_id,
        )


class SQLAApiKey(SQLABase):
    __tablename__ = TABLE_API_KEY

    id = mapped_column(String(36), primary_key=True)
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True)
    name = mapped_column(Text, nullable=False)
    key_hash = mapped_column(Text, nullable=False, unique=True, index=True)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
    disabled_at = mapped_column(DateTime, nullable=True, index=True)
    last_used_at = mapped_column(DateTime, nullable=True, index=True)

    user: Mapped["SQLAUser"] = relationship("SQLAUser", backref="api_keys")

    @property
    def is_active(self) -> bool:
        return self.disabled_at is None


class SQLATelemetryLog(SQLABase):
    __tablename__ = TABLE_TELEMETRY_LOG

    id = mapped_column(String(36), primary_key=True)
    user_id = mapped_column(String(36), ForeignKey(f"{TABLE_USER}.id"), nullable=False, index=True)
    collection_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_COLLECTION}.id"), nullable=True, index=True
    )
    # Explicit type/category for this telemetry entry (e.g., "traces", "scores", "metadata", "trace-done")
    type = mapped_column(Text, nullable=True)
    version = mapped_column(Text, nullable=True)
    json_data = mapped_column(JSONB, nullable=False)
    created_at = mapped_column(
        DateTime, default=lambda: datetime.now(UTC).replace(tzinfo=None), nullable=False
    )
