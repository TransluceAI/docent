from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


@dataclass
class ToolCall:
    """Tool call information.

    Attributes:
        id: Unique identifier for tool call.
        type: Type of tool call. Can only be "function" or None.
        function: Function called.
        arguments: Arguments to function.
        parse_error: Error which occurred parsing tool call.
        view: Custom view of tool call input.
    """

    id: str
    function: str
    arguments: dict[str, Any]
    type: Literal["function"] | None = None
    parse_error: str | None = None
    view: ToolCallContent | None = None


class ToolCallContent(BaseModel):
    """Content to include in tool call view.

    Attributes:
        title: Optional (plain text) title for tool call content.
        format: Format (text or markdown).
        content: Text or markdown content.
    """

    title: str | None = None
    format: Literal["text", "markdown"]
    content: str


class ToolParam(BaseModel):
    """A parameter for a tool function.

    Args:
        name: The name of the parameter.
        description: A description of what the parameter does.
        input_schema: JSON Schema describing the parameter's type and validation rules.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


class ToolParams(BaseModel):
    """Description of tool parameters object in JSON Schema format.

    Args:
        type: The type of the parameters object, always 'object'.
        properties: Dictionary mapping parameter names to their ToolParam definitions.
        required: List of required parameter names.
        additionalProperties: Whether additional properties are allowed beyond those
            specified. Always False.
    """

    type: Literal["object"] = "object"
    properties: dict[str, ToolParam] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additionalProperties: bool = False


class ToolInfo(BaseModel):
    """Specification of a tool (JSON Schema compatible).

    If you are implementing a ModelAPI, most LLM libraries can
    be passed this object (dumped to a dict) directly as a function
    specification. For example, in the OpenAI provider:

    ```python
    ChatCompletionToolParam(
        type="function",
        function=tool.model_dump(exclude_none=True),
    )
    ```

    In some cases the field names don't match up exactly. In that case
    call `model_dump()` on the `parameters` field. For example, in the
    Anthropic provider:

    ```python
    ToolParam(
        name=tool.name,
        description=tool.description,
        input_schema=tool.parameters.model_dump(exclude_none=True),
    )
    ```

    Attributes:
        name: Name of tool.
        description: Short description of tool.
        parameters: JSON Schema of tool parameters object.
    """

    name: str
    description: str
    parameters: ToolParams = Field(default_factory=ToolParams)
