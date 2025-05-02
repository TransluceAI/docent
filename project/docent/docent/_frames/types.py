from __future__ import annotations

from typing import Any, Protocol
from uuid import uuid4

from docent._frames.transcript import Transcript, TranscriptMetadata
from pydantic import BaseModel, Field


class Datapoint(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    attributes: dict[str, list[str]] = Field(default_factory=dict)
    obj: Transcript

    @property
    def metadata(self) -> TranscriptMetadata:
        return self.obj.metadata

    @property
    def text(self) -> str:
        return self.obj.to_str()

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return super().model_dump(*args, **kwargs) | {"text": self.text}

    @classmethod
    def from_transcript(cls, transcript: Transcript, id_prefix: str | None = None) -> Datapoint:
        return cls(
            obj=transcript,
            name=f"{id_prefix}_{transcript.metadata.task_id}_{transcript.metadata.sample_id}_{transcript.metadata.experiment_id}_{transcript.metadata.epoch_id}".replace(
                "/", "_"
            ),
        )


class Judgment(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    data_id: str
    attribute: str | None = None
    attribute_idx: int | None = None

    matches: bool
    reason: str | None = None


class Attribute(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    data_id: str
    attribute: str
    attribute_idx: int | None = None
    value: str | None = None


class AssignmentStreamingCallback(Protocol):
    async def __call__(
        self,
        batch_index: int,
        assignment: tuple[bool, str] | None,
    ) -> None: ...


class JudgmentStreamingCallback(Protocol):
    async def __call__(
        self,
        data_index: int,
        attribute_index: int,
        judgment: Judgment,
    ) -> None: ...


class RegexSnippet(BaseModel):
    snippet: str
    match_start: int
    match_end: int
