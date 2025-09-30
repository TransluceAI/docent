"""Judge-related data models shared across Docent components."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JudgeRunLabel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    rubric_id: str
    label: dict[str, Any]


__all__ = ["JudgeRunLabel"]
