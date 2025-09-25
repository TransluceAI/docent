from abc import ABC, abstractmethod
from typing import AsyncIterator

from docent.data_models.chat.message import ChatMessage
from docent_core.investigator.tools.common.types import (
    MessageEnd,
    MessageStart,
    RolloutEnd,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
)


class BaseContextPolicy(ABC):
    """
    The base class for all context policies.

    A `context policy` specifies a distribution over contexts--in this case, by appending user
    messages to an existing conversation. When conditioned on a new assistant response, the context
    policy should stream user tokens for the next response. It should always yield a `MessageStart`,
    followed by `TokenDelta` events, followed by a `MessageEnd` event. If streaming is not needed
    (e.g. the actions are deterministic strings, not samples from a language model), then stream a
    `TokenDelta` event with the entire generated response.

    Context policies need not be stateless! A single context policy will be created for each
    conversation. In fact, it is probably important for a context policy to track the state, given
    that it only receives the previous turn of the subject model a context policy to track the
    state, given that it only receives the previous turn of the subject model at each iteration.


    """

    @abstractmethod
    async def generate_message_stream(
        self,
        subject_model_turn: list[ChatMessage],
    ) -> AsyncIterator[
        MessageStart
        | TokenDelta
        | MessageEnd
        | RolloutEnd
        | ToolCallStart
        | ToolCallDelta
        | ToolCallEnd
    ]:
        """
        Generate the next user message given the previous turn of the subject model.

        Args:
            subject_model_turn: List of the message(s) from the previous turn of the subject model.
            If the policy is proposing the first message, this will be empty.

        Yields:
            Events in the order: MessageStart -> TokenDelta(s) -> MessageEnd ->
            (possibly RolloutEnd, if it is the last turn)
        """
        yield MessageStart(  # needed for typechecking
            role="user",
            is_thinking=False,
        )
        raise NotImplementedError("Subclasses must implement this method")
