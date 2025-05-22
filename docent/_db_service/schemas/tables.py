import json
from datetime import UTC, datetime

from pydantic_core import to_jsonable_python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column
from sqlalchemy.schema import UniqueConstraint

from docent._ai_tools.attribute_extraction import Attribute
from docent._db_service.schemas.base import SQLABase
from docent.data_models.agent_run import AgentRun
from docent.data_models.filters import FrameDimension, FrameFilter, Judgment, parse_filter_dict
from docent.data_models.transcript import Transcript

TABLE_FRAME_GRID = "frame_grids"
TABLE_AGENT_RUN = "agent_runs"
TABLE_ATTRIBUTE = "attributes"
TABLE_FRAME_DIMENSION = "frame_dimensions"
TABLE_FILTER = "filters"
TABLE_JUDGMENT = "judgments"
TABLE_JOB = "jobs"
TABLE_TRANSCRIPT = "transcripts"


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

    base_filter_id = mapped_column(String(36), ForeignKey(f"{TABLE_FILTER}.id"), index=True)
    outer_dim_id = mapped_column(String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"))
    inner_dim_id = mapped_column(String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"))

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

    # For predicate dimensions
    attribute = mapped_column(Text, index=True)
    backend = mapped_column(Text, nullable=False)

    # For metadata dimensions
    metadata_key = mapped_column(Text, index=True)
    maintain_mece = mapped_column(Boolean, index=True)

    # Loading state
    loading_clusters = mapped_column(Boolean, nullable=False)
    loading_marginals = mapped_column(Boolean, nullable=False)

    @classmethod
    def from_frame_dimension(cls, dimension: FrameDimension, fg_id: str):
        """Convert a FrameDimension object to a SQLAFrameDimension object for database storage."""
        sqla_dimension = cls(
            id=dimension.id,
            name=dimension.name,
            fg_id=fg_id,
            attribute=dimension.attribute,
            backend=dimension.backend,
            metadata_key=dimension.metadata_key,
            maintain_mece=dimension.maintain_mece,
            loading_clusters=dimension.loading_clusters,
            loading_marginals=dimension.loading_marginals,
        )

        # Add filters if they exist
        filters: list[SQLAFilter] = []
        if dimension.bins:
            for filter_obj in dimension.bins:
                filters.append(SQLAFilter.from_filter(filter_obj, fg_id, dimension.id))

        return sqla_dimension, filters

    def to_frame_dimension(self, filters: list[FrameFilter] | None) -> FrameDimension:
        return FrameDimension(
            id=self.id,
            name=self.name,
            bins=filters,
            attribute=self.attribute,
            backend=self.backend,
            metadata_key=self.metadata_key,
            maintain_mece=self.maintain_mece,
            loading_clusters=self.loading_clusters,
            loading_marginals=self.loading_marginals,
        )


class SQLAFilter(SQLABase):
    __tablename__ = TABLE_FILTER

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

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
        fg_id: str,
        dim_id: str | None,
    ):
        return cls(
            id=filter.id,
            fg_id=fg_id,
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

    # Key that must remain unique
    uniqueness_key = mapped_column(Text, nullable=False, unique=True)

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
    attribute = mapped_column(Text, index=True)
    attribute_idx = mapped_column(Integer, index=True)

    # The judgment result
    matches = mapped_column(Boolean, nullable=False, index=True)
    reason = mapped_column(Text)

    @classmethod
    def from_judgment(cls, judgment: Judgment, fg_id: str) -> "SQLAJudgment":
        uniqueness_key = f"{fg_id}|{judgment.filter_id}|{judgment.agent_run_id}|{judgment.attribute}|{judgment.attribute_idx}"

        return cls(
            id=judgment.id,
            fg_id=fg_id,
            uniqueness_key=uniqueness_key,
            agent_run_id=judgment.agent_run_id,
            filter_id=judgment.filter_id,
            attribute=judgment.attribute,
            attribute_idx=judgment.attribute_idx,
            matches=judgment.matches,
            reason=judgment.reason,
        )

    def to_judgment(self) -> Judgment:
        return Judgment(
            id=self.id,
            agent_run_id=self.agent_run_id,
            filter_id=self.filter_id,
            attribute=self.attribute,
            attribute_idx=self.attribute_idx,
            matches=self.matches,
            reason=self.reason,
        )


class SQLAAttribute(SQLABase):
    __tablename__ = TABLE_ATTRIBUTE

    id = mapped_column(String(36), primary_key=True)
    fg_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Location of the attribute
    agent_run_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_AGENT_RUN}.id"), nullable=False, index=True
    )
    attribute = mapped_column(Text, nullable=False, index=True)
    attribute_idx = mapped_column(Integer, index=True)

    # Null indicates no values for this (datapoint, attribute) pair
    # If there are any non-null values, value should never be null
    value = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "fg_id",
            "agent_run_id",
            "attribute",
            "attribute_idx",
            name="uq_attribute_key_combination",
        ),
    )

    @classmethod
    def from_attribute(
        cls,
        attribute: Attribute,
        fg_id: str,
    ):
        return cls(
            id=attribute.id,
            fg_id=fg_id,
            agent_run_id=attribute.agent_run_id,
            attribute=attribute.attribute,
            attribute_idx=attribute.attribute_idx,
            value=attribute.value,
        )

    def to_attribute(self) -> Attribute:
        return Attribute(
            id=self.id,
            agent_run_id=self.agent_run_id,
            attribute=self.attribute,
            attribute_idx=self.attribute_idx,
            value=self.value,
        )


class SQLAJob(SQLABase):
    __tablename__ = TABLE_JOB

    id = mapped_column(String(36), primary_key=True)
    job_json = mapped_column(JSONB, nullable=False)
