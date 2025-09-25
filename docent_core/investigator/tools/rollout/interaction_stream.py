import json
from typing import Any, AsyncIterator, TypedDict

from docent.data_models.chat import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
    UserMessage,
)
from docent_core.investigator.tools.common.types import (
    MessageEnd,
    MessageStart,
    RolloutEnd,
    StreamEvent,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
)
from docent_core.investigator.tools.judges.base import JudgeBase
from docent_core.investigator.tools.policies.base import BaseContextPolicy
from docent_core.investigator.tools.subject_models.base import SubjectModelBase


class ToolCallTrackingData(TypedDict):
    """Data structure for tracking tool call information during streaming."""

    id: str
    name: str
    arguments: str
    type: str  # "function" or "custom"


async def generate_interaction_stream(
    policy: BaseContextPolicy,
    subject_model: SubjectModelBase,
    grader: JudgeBase,
) -> AsyncIterator[StreamEvent]:
    """Generate a conversation transcript using a context policy with streaming updates.

    This function orchestrates an interaction between a policy (which generates user messages)
    and a subject model (which generates assistant responses), streaming all events in real-time,
    followed by grading the resulting conversation.

    The interaction flow is:
    1. Policy generates one or more user messages based on the previous subject model turn
    2. Subject model generates one or more assistant responses to the policy messages
    3. Steps 1-2 repeat until the policy signals end of rollout
    4. The complete conversation is graded

    Args:
        policy: A context policy that generates user messages based on the previous subject
                model turn. The policy can generate multiple messages per turn and controls
                when the conversation ends by yielding RolloutEnd.
        subject_model: The model being investigated, which generates assistant responses
                      to policy messages. Can generate multiple messages per turn.
        grader: A judge that evaluates the final conversation transcript for the
                target behavior or criteria.

    Yields:
        StreamEvent: A sequence of events in the following order:
            - For each turn:
                * Policy messages (one or more):
                    - MessageStart (role="user") - Start of policy message
                    - TokenDelta(s) - Incremental policy message content
                    - MessageEnd - End of policy message
                * Subject model responses (one or more):
                    - MessageStart (role="assistant") - Start of subject model response
                    - TokenDelta(s) - Incremental subject model response content
                    - MessageEnd - End of subject model response
            - After all turns:
                * RolloutEnd - Indicates conversation is complete
                * GradeStart - Beginning of grading process
                * GradeUpdate(s) - Incremental grading information
                * GradeEnd - Final grade with complete evaluation

    Example:
        >>> async for event in generate_interaction_stream(
        ...     policy=my_policy,
        ...     subject_model=my_model,
        ...     grader=my_grader
        ... ):
        ...     if isinstance(event, TokenDelta):
        ...         print(event.content, end="")
        ...     elif isinstance(event, MessageEnd):
        ...         print()  # New line after message
        ...     elif isinstance(event, GradeEnd):
        ...         print(f"Grade: {event.annotation.grade}")
    """
    conversation_history: list[ChatMessage] = []
    last_subject_model_turn: list[ChatMessage] = []

    while True:
        # Generate policy message(s) based on current conversation state
        policy_turn_messages: list[ChatMessage] = []
        current_message_content = ""
        current_message_id = None
        current_message_role: str | None = None
        current_tool_call_id: str | None = None
        current_tool_calls: dict[int, ToolCallTrackingData] = {}
        rollout_ended = False

        async for event in policy.generate_message_stream(
            subject_model_turn=last_subject_model_turn
        ):
            if isinstance(event, MessageStart):
                current_message_id = event.message_id
                current_message_content = ""
                current_message_role = event.role
                current_tool_call_id = event.tool_call_id
                current_tool_calls = {}
                yield event
            elif isinstance(event, TokenDelta):
                current_message_content += event.content
                yield event
            elif isinstance(event, ToolCallStart):
                if event.tool_call_index not in current_tool_calls:
                    current_tool_calls[event.tool_call_index] = ToolCallTrackingData(
                        id=event.tool_call_id,
                        name=event.function_name,
                        arguments="",
                        type=event.type,
                    )
                yield event
            elif isinstance(event, ToolCallDelta):
                if event.tool_call_index in current_tool_calls:
                    current_tool_calls[event.tool_call_index]["arguments"] += event.arguments_delta
                yield event
            elif isinstance(event, ToolCallEnd):
                yield event
            elif isinstance(event, MessageEnd):
                # Construct the complete message and add to history
                if current_message_role is not None and current_message_id is not None:
                    policy_message_tool_calls: list[ToolCall] | None = None
                    if current_tool_calls:
                        policy_message_tool_calls = []
                        for tool_data in current_tool_calls.values():
                            try:
                                parsed_args = (
                                    json.loads(tool_data["arguments"])
                                    if tool_data["arguments"]
                                    else {}
                                )
                            except json.JSONDecodeError:
                                parsed_args = {"raw": tool_data["arguments"]}

                            policy_message_tool_calls.append(
                                ToolCall(
                                    id=tool_data["id"],
                                    function=tool_data["name"],
                                    arguments=parsed_args,
                                    type="function",  # type: ignore[arg-type]
                                )
                            )

                    if current_message_role == "user":
                        policy_message = UserMessage(
                            id=current_message_id,
                            content=current_message_content,
                        )
                    elif current_message_role == "assistant":
                        policy_message = AssistantMessage(
                            id=current_message_id,
                            content=current_message_content,
                            tool_calls=policy_message_tool_calls,
                        )
                    elif current_message_role == "system":
                        policy_message = SystemMessage(
                            id=current_message_id,
                            content=current_message_content,
                        )
                    elif current_message_role == "tool":
                        policy_message = ToolMessage(
                            id=current_message_id,
                            content=current_message_content,
                            tool_call_id=current_tool_call_id,
                        )
                    else:
                        raise ValueError(f"Unsupported message role: {current_message_role}")

                    policy_turn_messages.append(policy_message)
                    conversation_history.append(policy_message)

                current_message_role = None
                current_tool_call_id = None
                current_tool_calls = {}
                yield event
            elif isinstance(event, RolloutEnd):  # type: ignore[misc]
                rollout_ended = True
                # Don't yield RolloutEnd yet - wait until after subject model response
                # TODO(neil): should we just require that RolloutEnd can only be called in a turn
                # by itself?

        # If rollout ended and no messages were generated, end the conversation
        if rollout_ended and not policy_turn_messages:
            yield RolloutEnd()
            break

        # Generate subject model response
        if policy_turn_messages:
            subject_model_turn_messages: list[ChatMessage] = []
            current_message_content = ""
            current_message_id = None
            tool_calls_data: dict[int, ToolCallTrackingData] = {}  # Track tool calls by index

            async for event in subject_model.generate_response_stream(
                policy_turn=policy_turn_messages
            ):
                if isinstance(event, MessageStart):
                    current_message_id = event.message_id
                    current_message_content = ""
                    tool_calls_data = {}  # Reset tool calls for new message
                    yield event
                elif isinstance(event, TokenDelta):
                    current_message_content += event.content
                    yield event
                elif isinstance(event, ToolCallStart):
                    # Initialize tool call tracking
                    if event.tool_call_index not in tool_calls_data:
                        tool_calls_data[event.tool_call_index] = ToolCallTrackingData(
                            id=event.tool_call_id,
                            name=event.function_name,
                            arguments="",
                            type=getattr(
                                event, "type", "function"
                            ),  # Default to 'function' if not specified
                        )
                    yield event
                elif isinstance(event, ToolCallDelta):
                    # Accumulate tool call arguments
                    if event.tool_call_index in tool_calls_data:
                        tool_calls_data[event.tool_call_index]["arguments"] += event.arguments_delta
                    yield event
                elif isinstance(event, ToolCallEnd):
                    # Tool call is complete, no additional processing needed here
                    yield event
                elif isinstance(event, MessageEnd):  # type: ignore[misc]
                    # Construct the complete message and add to history
                    # Build tool calls list if any
                    tool_calls: list[ToolCall] | None = None
                    if tool_calls_data:
                        tool_calls = []
                        for tool_data in tool_calls_data.values():

                            # For function calls, try to parse arguments as JSON
                            parsed_args: dict[str, Any]
                            try:
                                parsed_args = (
                                    json.loads(tool_data["arguments"])
                                    if tool_data["arguments"]
                                    else {}
                                )
                            except json.JSONDecodeError:
                                # If parsing fails, store as dict with raw key
                                parsed_args = {"raw": tool_data["arguments"]}

                            tool_calls.append(
                                ToolCall(
                                    id=tool_data["id"],
                                    function=tool_data["name"],
                                    arguments=parsed_args,
                                    type="function",
                                )
                            )

                    # Create assistant message with content and/or tool calls
                    assistant_message = AssistantMessage(
                        id=current_message_id,
                        content=current_message_content if current_message_content else "",
                        tool_calls=tool_calls,
                    )
                    subject_model_turn_messages.append(assistant_message)
                    conversation_history.append(assistant_message)
                    yield event

            # Update the last subject model turn for the next policy iteration
            last_subject_model_turn = subject_model_turn_messages

        # If policy signaled end of rollout, break after subject model response
        if rollout_ended:
            yield RolloutEnd()
            break

    # Stream grading events
    async for grade_event in grader.grade_transcript_stream(conversation_history):
        yield grade_event
