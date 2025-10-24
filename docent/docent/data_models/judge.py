"""Judge-related data models shared across Docent components."""

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Label(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))

    label_set_id: str

    label_value: dict[str, Any]

    agent_run_id: str


__all__ = ["Label"]
