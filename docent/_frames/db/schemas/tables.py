"""
FIXME(mengk): add indices to commonly-filtered columns
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

from pydantic_core import to_jsonable_python
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column
from sqlalchemy.schema import UniqueConstraint

from docent._frames.db.schemas.base import SQLABase
from docent._frames.filters import FrameDimension, FrameFilterTypes, parse_filter_dict
from docent._frames.transcript import Transcript
from docent._frames.types import Attribute, Datapoint, Judgment

# Table names
TABLE_FRAME_GRID = "frame_grids"
TABLE_DATAPOINT = "datapoints"
TABLE_ATTRIBUTE = "attributes"
TABLE_FRAME_DIMENSION = "frame_dimensions"
TABLE_FILTER = "filters"
TABLE_JUDGMENT = "judgments"
TABLE_JOB = "jobs"


def _sanitize_pg_text(text: str) -> str:
    """
    Wow this took almost an hour to debug.
    Postgres rejects strings with \\x00 and \\u0000, but it turns out that
    JSONifying data converts them to the literal characters \\, x, 0, 0.
    """
    return text.translate({0: None}).replace("\\x00", "").replace("\\u0000", "")


class SQLADatapoint(SQLABase):
    __tablename__ = TABLE_DATAPOINT

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    frame_grid_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Core messages data field
    # Content might contain invalid chars, so store as raw bytes
    messages = mapped_column(LargeBinary, nullable=False)

    # Metdata columns as JSONB so they can be keyed into
    # A scan is fine for ~1e4 transcripts; if larger we might want to index
    metadata_json = mapped_column(JSONB, nullable=False)

    # This column is *only* used for regex search; it needs to be preprocessed to remove invalid characters
    text_for_search = mapped_column(Text, nullable=False)

    @classmethod
    def from_datapoint(cls, datapoint: Datapoint, fg_id: str) -> "SQLADatapoint":
        # Serialize to JSON and then convert to bytes to avoid encoding issues
        messages_binary = json.dumps(to_jsonable_python(datapoint.obj.messages)).encode("utf-8")
        # Sanitize raw text
        metadata_json = json.loads(_sanitize_pg_text(datapoint.metadata.model_dump_json()))
        text_for_search = _sanitize_pg_text(datapoint.text)

        return cls(
            id=datapoint.id,
            frame_grid_id=fg_id,
            name=datapoint.name,
            messages=messages_binary,
            metadata_json=metadata_json,
            text_for_search=text_for_search,
        )

    def to_datapoint(self) -> Datapoint:
        messages = json.loads(self.messages.decode("utf-8"))
        transcript = Transcript(messages=messages, metadata=self.metadata_json)
        return Datapoint(id=self.id, name=self.name, obj=transcript)


class SQLAFrameGrid(SQLABase):
    __tablename__ = TABLE_FRAME_GRID

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    description = mapped_column(Text)

    base_filter_id = mapped_column(String(36), ForeignKey(f"{TABLE_FILTER}.id"), index=True)
    sample_dim_id = mapped_column(String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"))
    experiment_dim_id = mapped_column(String(36), ForeignKey(f"{TABLE_FRAME_DIMENSION}.id"))

    created_at = mapped_column(DateTime, default=lambda: datetime.now(UTC), nullable=False)


class SQLAFrameDimension(SQLABase):
    __tablename__ = TABLE_FRAME_DIMENSION

    id = mapped_column(String(36), primary_key=True)
    name = mapped_column(Text)
    frame_grid_id = mapped_column(
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
            frame_grid_id=fg_id,
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

    def to_frame_dimension(self, filters: list[FrameFilterTypes] | None) -> FrameDimension:
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
    frame_grid_id = mapped_column(
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
        filter: FrameFilterTypes,
        fg_id: str,
        dim_id: str | None,
    ):
        return cls(
            id=filter.id,
            frame_grid_id=fg_id,
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
    frame_grid_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Key that must remain unique
    uniqueness_key = mapped_column(Text, nullable=False, unique=True)

    # Metadata on the location of the judgment
    filter_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FILTER}.id"), nullable=False, index=True
    )
    datapoint_id = mapped_column(
        String(36),
        ForeignKey(f"{TABLE_DATAPOINT}.id"),
        nullable=False,
        index=True,
    )
    attribute = mapped_column(Text, index=True)
    attribute_idx = mapped_column(Integer, index=True)

    # The judgment result
    matches = mapped_column(Boolean, nullable=False, index=True)
    reason = mapped_column(Text)

    @classmethod
    def from_judgment(cls, judgment: Judgment, fg_id: str, filter_id: str) -> "SQLAJudgment":
        uniqueness_key = (
            f"{fg_id}|{filter_id}|{judgment.data_id}|{judgment.attribute}|{judgment.attribute_idx}"
        )

        return cls(
            id=judgment.id,
            frame_grid_id=fg_id,
            uniqueness_key=uniqueness_key,
            filter_id=filter_id,
            datapoint_id=judgment.data_id,
            matches=judgment.matches,
            attribute=judgment.attribute,
            attribute_idx=judgment.attribute_idx,
            reason=judgment.reason,
        )

    def to_judgment(self) -> Judgment:
        return Judgment(
            id=self.id,
            data_id=self.datapoint_id,
            attribute=self.attribute,
            attribute_idx=self.attribute_idx,
            matches=self.matches,
            reason=self.reason,
        )


class SQLAAttribute(SQLABase):
    __tablename__ = TABLE_ATTRIBUTE

    id = mapped_column(String(36), primary_key=True)
    frame_grid_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_FRAME_GRID}.id"), nullable=False, index=True
    )

    # Location of the attribute
    datapoint_id = mapped_column(
        String(36), ForeignKey(f"{TABLE_DATAPOINT}.id"), nullable=False, index=True
    )
    attribute = mapped_column(Text, nullable=False, index=True)
    attribute_idx = mapped_column(Integer, index=True)

    # Null indicates no values for this (datapoint, attribute) pair
    # If there are any non-null values, value should never be null
    value = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "frame_grid_id",
            "datapoint_id",
            "attribute",
            "attribute_idx",
            name="uq_attribute_key_combination",
        ),
    )

    @classmethod
    def from_attribute(
        cls,
        datapoint_id: str,
        attribute: str,
        attribute_idx: int | None,
        value: str | None,
        fg_id: str,
    ):
        return cls(
            id=str(uuid4()),
            frame_grid_id=fg_id,
            datapoint_id=datapoint_id,
            attribute=attribute,
            attribute_idx=attribute_idx,
            value=value,
        )

    def to_attribute(self) -> Attribute:
        return Attribute(
            id=self.id,
            data_id=self.datapoint_id,
            attribute=self.attribute,
            attribute_idx=self.attribute_idx,
            value=self.value,
        )


class SQLAJob(SQLABase):
    __tablename__ = TABLE_JOB

    id = mapped_column(String(36), primary_key=True)
    job_json = mapped_column(JSONB, nullable=False)
