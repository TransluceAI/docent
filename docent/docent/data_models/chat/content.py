from typing import Annotated, Literal

from pydantic import BaseModel, Discriminator


class BaseContent(BaseModel):
    """Base class for all content types in chat messages.

    Provides the foundation for different content types with a discriminator field.

    Attributes:
        type: The content type identifier, used for discriminating between content types.
    """

    type: Literal["text", "reasoning", "image", "audio", "video"]


class ContentText(BaseContent):
    """Text content for chat messages.

    Represents plain text content in a chat message.

    Attributes:
        type: Fixed as "text" to identify this content type.
        text: The actual text content.
        refusal: Optional flag indicating if this is a refusal message.
    """

    type: Literal["text"] = "text"  # type: ignore
    text: str
    refusal: bool | None = None


class ContentReasoning(BaseContent):
    """Reasoning content for chat messages.

    Represents reasoning or thought process content in a chat message.

    Attributes:
        type: Fixed as "reasoning" to identify this content type.
        reasoning: The actual reasoning text.
        signature: Optional signature associated with the reasoning.
        redacted: Flag indicating if the reasoning has been redacted.
    """

    type: Literal["reasoning"] = "reasoning"  # type: ignore
    reasoning: str
    signature: str | None = None
    redacted: bool = False


# Content type discriminated union
Content = Annotated[ContentText | ContentReasoning, Discriminator("type")]
"""Discriminated union of possible content types using the 'type' field.
Can be either ContentText or ContentReasoning.
"""
