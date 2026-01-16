"""Response format specification for structured outputs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ResponseFormat(BaseModel):
    """Unified response format specification for structured outputs.

    Supports JSON Schema-based constrained decoding across LLM providers.
    Each provider converts this to their specific format:
    - OpenAI: response_format parameter
    - Anthropic: output_format parameter (with beta header)
    - OpenRouter: response_format parameter (same as OpenAI)

    Attributes:
        type: The format type. Currently only "json_schema" is supported.
        name: A name for the schema (required by all providers).
        schema_: The JSON Schema definition as a dict.
        strict: Whether to enforce strict schema adherence (default True).

    Example:
        ```python
        response_format = ResponseFormat(
            name="analysis_result",
            schema={
                "type": "object",
                "properties": {
                    "score": {"type": "number"},
                    "explanation": {"type": "string"},
                },
                "required": ["score", "explanation"],
            },
        )
        ```
    """

    type: Literal["json_schema"] = "json_schema"
    name: str
    # Named `schema_` to avoid conflict with Pydantic's internal schema methods
    schema_: dict[str, Any] = Field(alias="schema")
    strict: bool = True

    model_config = {"populate_by_name": True}
