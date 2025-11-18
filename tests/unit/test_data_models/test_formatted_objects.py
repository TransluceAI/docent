"""Unit tests for FormattedTranscript and FormattedAgentRun."""

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, UserMessage
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.data_models.transcript import Transcript


@pytest.mark.unit
def test_formatted_transcript_preserves_indices_after_deletion():
    """Test that deleting messages from FormattedTranscript maintains correct indices in to_str()."""
    transcript = Transcript(
        id="t1",
        messages=[
            UserMessage(id="msg0", content="Message 0"),
            AssistantMessage(id="msg1", content="Message 1"),
            UserMessage(id="msg2", content="Message 2"),
        ],
        metadata={},
    )

    formatted = FormattedTranscript.from_transcript(transcript)
    # Keep messages 0 and 2, delete message 1
    formatted.messages = [formatted.messages[0], formatted.messages[2]]

    output = formatted.to_text_new("T0")

    assert "T0B0" in output
    assert "T0B2" in output
    assert "T0B1" not in output


@pytest.mark.unit
def test_formatted_agent_run_serialization_preserves_id_to_original_index():
    """Test that FormattedAgentRun serialization/deserialization preserves id_to_original_index."""
    msg1 = UserMessage(content="Hello")
    msg2 = AssistantMessage(content="Hi there")
    msg3 = UserMessage(content="How are you?")

    transcript = Transcript(id="t1", messages=[msg1, msg2, msg3], metadata={})
    formatted_transcript = FormattedTranscript.from_transcript(transcript)

    original_id_to_idx = formatted_transcript.id_to_original_index.copy()

    formatted_agent_run = FormattedAgentRun(
        id="ar1", transcripts=[formatted_transcript], metadata={}
    )

    assert isinstance(formatted_agent_run.transcripts[0], FormattedTranscript)
    assert formatted_agent_run.transcripts[0].id_to_original_index == original_id_to_idx

    serialized = formatted_agent_run.model_dump()

    assert "id_to_original_index" in serialized["transcripts"][0]
    assert serialized["transcripts"][0]["id_to_original_index"] == original_id_to_idx

    deserialized = FormattedAgentRun(**serialized)

    assert isinstance(deserialized.transcripts[0], FormattedTranscript)
    assert deserialized.transcripts[0].id_to_original_index == original_id_to_idx


@pytest.mark.unit
def test_formatted_agent_run_from_plain_agent_run_requires_from_agent_run():
    """Test that you must use from_agent_run() to convert a plain AgentRun."""
    msg1 = UserMessage(content="Hello")
    msg2 = AssistantMessage(content="Hi there")

    transcript = Transcript(id="t1", messages=[msg1, msg2], metadata={})
    plain_agent_run = AgentRun(id="ar1", transcripts=[transcript], metadata={})

    plain_serialized = plain_agent_run.model_dump()

    assert "id_to_original_index" not in plain_serialized["transcripts"][0]

    # Direct deserialization should fail because id_to_original_index is missing
    with pytest.raises(Exception):  # ValidationError
        FormattedAgentRun(**plain_serialized)

    # Must use from_agent_run() instead
    formatted_agent_run = FormattedAgentRun.from_agent_run(plain_agent_run)

    assert isinstance(formatted_agent_run.transcripts[0], FormattedTranscript)
    assert len(formatted_agent_run.transcripts[0].id_to_original_index) == 2

    for msg_idx, msg in enumerate(formatted_agent_run.transcripts[0].messages):
        assert msg.id in formatted_agent_run.transcripts[0].id_to_original_index
        assert formatted_agent_run.transcripts[0].id_to_original_index[msg.id] == msg_idx


@pytest.mark.unit
def test_formatted_agent_run_preserves_original_indices_after_message_deletion():
    """Test that id_to_original_index is truly serialized, not just recreated.

    This test creates a FormattedTranscript, removes a message, then serializes
    and deserializes. If id_to_original_index is properly preserved, the remaining
    messages should still point to their original indices, not their new positions.
    """
    msg0 = UserMessage(content="Message 0")
    msg1 = AssistantMessage(content="Message 1")
    msg2 = UserMessage(content="Message 2")

    transcript = Transcript(id="t1", messages=[msg0, msg1, msg2], metadata={})
    formatted_transcript = FormattedTranscript.from_transcript(transcript)

    msg0_id = formatted_transcript.messages[0].id
    msg2_id = formatted_transcript.messages[2].id
    assert msg0_id is not None
    assert msg2_id is not None

    original_msg2_idx = formatted_transcript.id_to_original_index[msg2_id]
    assert original_msg2_idx == 2

    formatted_transcript.messages = [
        formatted_transcript.messages[0],
        formatted_transcript.messages[2],
    ]

    formatted_agent_run = FormattedAgentRun(
        id="ar1", transcripts=[formatted_transcript], metadata={}
    )

    serialized = formatted_agent_run.model_dump()

    deserialized = FormattedAgentRun(**serialized)

    assert isinstance(deserialized.transcripts[0], FormattedTranscript)

    assert deserialized.transcripts[0].id_to_original_index[msg0_id] == 0
    assert deserialized.transcripts[0].id_to_original_index[msg2_id] == 2
