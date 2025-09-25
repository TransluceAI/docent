from abc import ABC, abstractmethod
from typing import AsyncIterator

from docent.data_models.chat import ChatMessage
from docent_core.investigator.tools.common.types import (
    MessageEnd,
    MessageStart,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    generate_uid,
)


class SubjectModelBase(ABC):
    """Base class for subject models that will be investigated.

    Note that this can (and probably should) be stateful!
    """

    @abstractmethod
    async def generate_response_stream(
        self,
        policy_turn: list[ChatMessage],
    ) -> AsyncIterator[
        TokenDelta | MessageStart | MessageEnd | ToolCallStart | ToolCallDelta | ToolCallEnd
    ]:
        """Generate a streaming response given the previous turn of the policy, which is a list of
        ChatMessages (generally system/user messages).

        Generally, this should respond with a single "assistant" message.
        """
        yield MessageEnd(  # needed for typechecking
            message_id=generate_uid(),
        )
        raise NotImplementedError("Not implemented")
