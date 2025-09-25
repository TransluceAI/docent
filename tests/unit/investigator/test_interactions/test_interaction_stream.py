"""Unit tests for interaction stream rollout."""

from typing import AsyncIterator

import pytest

from docent.data_models.chat import AssistantMessage, ChatMessage, UserMessage
from docent_core.investigator.tools.common.types import (
    GradeEnd,
    GradeStart,
    GradeUpdate,
    MessageEnd,
    MessageStart,
    RolloutEnd,
    StreamEvent,
    TokenDelta,
    generate_uid,
)
from docent_core.investigator.tools.judges.constant import ConstantJudge
from docent_core.investigator.tools.policies.deterministic import DeterministicContextPolicy
from docent_core.investigator.tools.rollout.interaction_stream import (
    generate_interaction_stream,
)
from docent_core.investigator.tools.subject_models.base import SubjectModelBase


class MockSubjectModel(SubjectModelBase):
    """A simple mock subject model for testing."""

    def __init__(self, responses: list[str]):
        """Initialize with a list of responses to cycle through."""
        self.responses = responses
        self.call_count = 0

    async def generate_response_stream(
        self,
        policy_turn: list[ChatMessage],
    ) -> AsyncIterator[TokenDelta | MessageStart | MessageEnd]:
        """Generate a mock response stream."""
        # Get the response for this turn (cycle if we run out)
        response_idx = self.call_count % len(self.responses)
        response = self.responses[response_idx]
        self.call_count += 1

        message_id = generate_uid()

        # Stream the response
        yield MessageStart(
            message_id=message_id,
            role="assistant",
            is_thinking=False,
        )

        # Simulate streaming by yielding the response in chunks
        chunk_size = 10
        for i in range(0, len(response), chunk_size):
            yield TokenDelta(
                message_id=message_id,
                role="assistant",
                content=response[i : i + chunk_size],
            )

        yield MessageEnd(message_id=message_id)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_basic_interaction_stream():
    """Test a basic interaction stream with constant judge and deterministic policy."""

    # Create a simple deterministic policy with two user messages
    policy_messages: list[ChatMessage] = [
        UserMessage(content="Hello, how are you?"),
        UserMessage(content="What's your favorite color?"),
    ]
    policy = DeterministicContextPolicy(policy_messages)

    # Create a mock subject model with predefined responses
    subject_model = MockSubjectModel(
        [
            "I'm doing well, thank you!",
            "My favorite color is blue.",
        ]
    )

    # Create a constant judge that always returns score 5.0
    judge = ConstantJudge(score=5.0)

    # Collect all stream events
    events: list[StreamEvent] = []
    async for event in generate_interaction_stream(
        policy=policy,
        subject_model=subject_model,
        grader=judge,
    ):
        events.append(event)

    # Verify the sequence of events
    # We should have: policy messages, subject responses, rollout end, then grading

    # Count different event types
    message_starts = [e for e in events if isinstance(e, MessageStart)]
    message_ends = [e for e in events if isinstance(e, MessageEnd)]
    token_deltas = [e for e in events if isinstance(e, TokenDelta)]
    rollout_ends = [e for e in events if isinstance(e, RolloutEnd)]
    grade_starts = [e for e in events if isinstance(e, GradeStart)]
    grade_ends = [e for e in events if isinstance(e, GradeEnd)]

    # Should have 3 messages total (2 from policy in one turn, 1 from subject)
    assert len(message_starts) == 3
    assert len(message_ends) == 3

    # Should have content tokens for all messages
    assert len(token_deltas) > 0

    # Should have exactly one rollout end
    assert len(rollout_ends) == 1

    # Should have grading events
    assert len(grade_starts) == 1
    assert len(grade_ends) == 1

    # The final grade should be 5.0 (from our constant judge)
    assert grade_ends[0].annotation.grade == 5.0

    # Verify the order: messages should come before rollout end, which comes before grading
    rollout_end_idx = events.index(rollout_ends[0])
    grade_start_idx = events.index(grade_starts[0])

    assert rollout_end_idx < grade_start_idx

    # All message events should come before rollout end
    for msg_event in message_starts + message_ends + token_deltas:
        assert events.index(msg_event) < rollout_end_idx


@pytest.mark.unit
@pytest.mark.asyncio
async def test_interaction_stream_message_roles():
    """Test that messages have the correct roles in the interaction stream."""

    # Create a single user message
    policy_messages: list[ChatMessage] = [UserMessage(content="What is 2+2?")]
    policy = DeterministicContextPolicy(policy_messages)

    subject_model = MockSubjectModel(["2+2 equals 4."])
    judge = ConstantJudge(score=10.0)

    # Track the roles of messages
    message_roles: list[str] = []

    async for event in generate_interaction_stream(
        policy=policy,
        subject_model=subject_model,
        grader=judge,
    ):
        if isinstance(event, MessageStart):
            message_roles.append(event.role)

    # Should have user message from policy, then assistant response from subject
    assert message_roles == ["user", "assistant"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_interaction_stream_with_empty_policy():
    """Test that an empty policy still works (immediately ends rollout)."""

    # Create an empty policy
    policy = DeterministicContextPolicy([])

    # Subject model shouldn't be called with empty policy
    subject_model = MockSubjectModel(["This shouldn't be called"])
    judge = ConstantJudge(score=0.0)

    events: list[StreamEvent] = []
    async for event in generate_interaction_stream(
        policy=policy,
        subject_model=subject_model,
        grader=judge,
    ):
        events.append(event)

    # Should still have rollout end and grading events
    rollout_ends = [e for e in events if isinstance(e, RolloutEnd)]
    grade_ends = [e for e in events if isinstance(e, GradeEnd)]

    assert len(rollout_ends) == 1
    assert len(grade_ends) == 1

    # No messages should have been generated
    message_starts = [e for e in events if isinstance(e, MessageStart)]
    assert len(message_starts) == 0

    # Subject model shouldn't have been called
    assert subject_model.call_count == 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_constant_judge_streaming():
    """Test that the constant judge's streaming works via the base class."""

    # Create a simple conversation
    conversation: list[ChatMessage] = [
        UserMessage(content="Hello"),
        AssistantMessage(content="Hi there!"),
    ]

    judge = ConstantJudge(score=7.5)

    # Test the streaming method (which is provided by the base class)
    events: list[StreamEvent] = []
    async for event in judge.grade_transcript_stream(conversation):
        events.append(event)

    # Should have start, update, and end events
    assert any(isinstance(e, GradeStart) for e in events)
    assert any(isinstance(e, GradeUpdate) for e in events)
    assert any(isinstance(e, GradeEnd) for e in events)

    # Get the final grade
    grade_end = [e for e in events if isinstance(e, GradeEnd)][0]
    assert grade_end.annotation.grade == 7.5
