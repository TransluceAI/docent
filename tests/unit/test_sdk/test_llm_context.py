"""Unit tests for LLMContext class."""

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, UserMessage
from docent.data_models.citation import (
    AgentRunMetadataItem,
    TranscriptBlockContentItem,
    TranscriptBlockMetadataItem,
    TranscriptMetadataItem,
)
from docent.data_models.transcript import Transcript
from docent.sdk.llm_context import _build_whitespace_flexible_regex  # type: ignore
from docent.sdk.llm_context import _find_pattern_in_text  # type: ignore
from docent.sdk.llm_context import (
    LLMContext,
    resolve_citations_with_context,
)


@pytest.fixture
def sample_transcript():
    """Create a sample transcript for testing."""
    return Transcript(
        id="transcript-123",
        messages=[
            UserMessage(content="Hello"),
            AssistantMessage(content="Hi there"),
        ],
        metadata={"start_time": "2024-01-01T00:00:00Z"},
    )


@pytest.fixture
def sample_agent_run(sample_transcript: Transcript) -> AgentRun:
    """Create a sample agent run with transcripts."""
    return AgentRun(
        id="agent-run-456",
        transcripts=[sample_transcript],
        metadata={"task_description": "Test task"},
    )


@pytest.mark.unit
def test_to_str_multiple_transcripts(sample_transcript: Transcript) -> None:
    """Test to_str with multiple transcripts."""
    transcript2 = Transcript(
        id="transcript-789",
        messages=[UserMessage(content="Second transcript")],
        metadata={},
    )

    context = LLMContext()
    context.add(sample_transcript)
    context.add(transcript2)

    result = context.to_str()

    assert "T0" in result
    assert "T1" in result
    assert "Hello" in result
    assert "Second transcript" in result


@pytest.mark.unit
def test_to_str_multiple_agent_runs(
    sample_agent_run: AgentRun, sample_transcript: Transcript
) -> None:
    """Test to_str with multiple agent runs."""
    transcript2 = Transcript(
        id="transcript-999",
        messages=[UserMessage(content="Third message")],
        metadata={},
    )
    agent_run2 = AgentRun(
        id="agent-run-789",
        transcripts=[transcript2],
        metadata={"task": "Second task"},
    )

    context = LLMContext()
    context.add(sample_agent_run)
    context.add(agent_run2)

    result = context.to_str()

    assert "R0" in result
    assert "R1" in result
    assert "T0" in result
    assert "T1" in result
    assert "Hello" in result
    assert "Third message" in result


@pytest.mark.unit
def test_add_multiple_transcripts(sample_transcript: Transcript) -> None:
    """Test adding multiple transcripts assigns sequential aliases."""
    transcript2 = Transcript(
        id="transcript-789",
        messages=[UserMessage(content="Test")],
        metadata={},
    )

    context = LLMContext()
    context.add(sample_transcript)
    context.add(transcript2)

    assert len(context.transcript_aliases) == 2
    assert context.transcript_aliases[0] == sample_transcript
    assert context.transcript_aliases[1] == transcript2
    assert context.root_items == ["T0", "T1"]


@pytest.mark.unit
def test_add_agent_run(sample_agent_run: AgentRun, sample_transcript: Transcript) -> None:
    """Test adding agent run also creates aliases for nested transcripts."""
    context = LLMContext()
    context.add(sample_agent_run)

    # Agent run should get R0 alias
    assert len(context.agent_run_aliases) == 1
    assert context.agent_run_aliases[0] == sample_agent_run
    assert context.get_item_by_alias("R0") == sample_agent_run

    # Nested transcript should also get T0 alias
    assert len(context.transcript_aliases) == 1
    assert context.transcript_aliases[0] == sample_transcript
    assert context.get_item_by_alias("T0") == sample_transcript

    # Only agent run should be in root_items
    assert context.root_items == ["R0"]


@pytest.mark.unit
def test_resolve_item_alias_transcript_block(sample_agent_run: AgentRun) -> None:
    """Test resolving T0B1 format citation."""
    context = LLMContext()
    context.add(sample_agent_run)

    resolved = context.resolve_item_alias("T0B1")

    assert isinstance(resolved, TranscriptBlockContentItem)
    assert resolved.transcript_id == "transcript-123"
    assert resolved.block_idx == 1
    assert resolved.agent_run_id == "agent-run-456"


@pytest.mark.unit
def test_resolve_item_alias_transcript_metadata(sample_agent_run: AgentRun) -> None:
    """Test resolving T0M.key format citation."""
    context = LLMContext()
    context.add(sample_agent_run)

    resolved = context.resolve_item_alias("T0M.start_time")

    assert isinstance(resolved, TranscriptMetadataItem)
    assert resolved.transcript_id == "transcript-123"
    assert resolved.metadata_key == "start_time"
    assert resolved.agent_run_id == "agent-run-456"


@pytest.mark.unit
def test_resolve_item_alias_block_metadata(sample_agent_run: AgentRun) -> None:
    """Test resolving T0B1M.key format citation."""
    context = LLMContext()
    context.add(sample_agent_run)

    resolved = context.resolve_item_alias("T0B1M.status")

    assert isinstance(resolved, TranscriptBlockMetadataItem)
    assert resolved.transcript_id == "transcript-123"
    assert resolved.block_idx == 1
    assert resolved.metadata_key == "status"
    assert resolved.agent_run_id == "agent-run-456"


@pytest.mark.unit
def test_resolve_item_alias_agent_run_metadata(sample_agent_run: AgentRun) -> None:
    """Test resolving R0M.key format citation."""
    context = LLMContext()
    context.add(sample_agent_run)

    resolved = context.resolve_item_alias("R0M.task_description")

    assert isinstance(resolved, AgentRunMetadataItem)
    assert resolved.agent_run_id == "agent-run-456"
    assert resolved.metadata_key == "task_description"


@pytest.mark.unit
def test_resolve_item_alias_nested_key_rejected():
    """Test that nested keys like T0M.status.code are rejected."""
    transcript = Transcript(id="t1", messages=[], metadata={"status": {"code": 200}})
    agent_run = AgentRun(id="ar1", transcripts=[transcript], metadata={})
    context = LLMContext()
    context.add(agent_run)

    with pytest.raises(ValueError, match="Nested keys are not allowed"):
        context.resolve_item_alias("T0M.status.code")


@pytest.mark.unit
def test_resolve_item_alias_invalid():
    """Test that invalid alias format raises ValueError."""
    context = LLMContext()

    with pytest.raises(ValueError, match="Unknown item alias"):
        context.resolve_item_alias("invalid")


@pytest.mark.unit
def test_resolve_citations_with_context(sample_agent_run: AgentRun) -> None:
    """Test end-to-end citation resolution."""
    context = LLMContext()
    context.add(sample_agent_run)

    text = "The agent [T0B1] said something about [T0M.start_time]."
    _, citations = resolve_citations_with_context(text, context)

    assert len(citations) == 2

    # First citation
    assert isinstance(citations[0].target.item, TranscriptBlockContentItem)
    assert citations[0].target.item.transcript_id == "transcript-123"
    assert citations[0].target.item.block_idx == 1

    # Second citation
    assert isinstance(citations[1].target.item, TranscriptMetadataItem)
    assert citations[1].target.item.transcript_id == "transcript-123"
    assert citations[1].target.item.metadata_key == "start_time"


@pytest.mark.unit
def test_resolve_citations_with_text_range(sample_agent_run: AgentRun) -> None:
    """Test citation resolution with text ranges (validation disabled)."""
    context = LLMContext()
    context.add(sample_agent_run)

    text = "The block [T0B1:<RANGE>specific text</RANGE>] contains this."
    _, citations = resolve_citations_with_context(text, context, validate_text_ranges=False)

    assert len(citations) == 1
    assert citations[0].target.text_range is not None
    assert citations[0].target.text_range.start_pattern == "specific text"


@pytest.mark.unit
def test_to_dict_agent_run(sample_agent_run: AgentRun) -> None:
    """Test serialization of context with agent run."""
    context = LLMContext()
    context.add(sample_agent_run)

    serialized = context.to_dict()

    assert serialized["root_items"] == ["R0"]
    assert serialized["agent_run_aliases"] == {"0": "agent-run-456"}
    assert serialized["transcript_aliases"] == {"0": "transcript-123"}
    assert "agent-run-456" not in serialized["formatted_data"]  # Not formatted
    assert serialized["transcript_to_agent_run"]["transcript-123"] == "agent-run-456"


@pytest.mark.unit
def test_get_system_message():
    """Test system message generation."""
    context = LLMContext()
    message = context.get_system_message()

    assert "analyzing transcripts" in message.lower()
    assert "citation" in message.lower()
    assert "<RANGE>" in message
    assert "</RANGE>" in message
    assert "T0B1" in message  # Example citation format


def create_test_agent_run() -> AgentRun:
    """Create a standardized mock AgentRun for all tests."""
    messages = [
        UserMessage(content="Hello, can you help?"),
        AssistantMessage(content="I understand the task and will help you."),
        UserMessage(content="Great, let's proceed."),
    ]
    transcript = Transcript(messages=messages)
    return AgentRun(
        id="test-run",
        transcripts=[transcript],
        transcript_groups=[],
    )


@pytest.mark.unit
def test_whitespace_flexible_regex():
    """Test whitespace flexible regex building."""
    pattern = "I understand the task"
    regex = _build_whitespace_flexible_regex(pattern)

    # Should match with different whitespace
    assert regex.search("I understand the task") is not None
    assert regex.search("I  understand   the    task") is not None
    assert regex.search("I\nunderstand\tthe    task") is not None

    # Should not match incomplete patterns
    assert regex.search("I understand") is None
    assert regex.search("understand the task") is None


@pytest.mark.unit
def test_citation_matching_scenarios():
    """Test various citation matching scenarios."""
    # Basic matching
    text = "The agent said I understand the task and continued."
    matches = _find_pattern_in_text(text, "I understand the task")
    assert len(matches) == 1
    assert text[matches[0][0] : matches[0][1]] == "I understand the task"

    # Multiple matches
    text = "First: I understand. Second: I understand again."
    matches = _find_pattern_in_text(text, "I understand")
    assert len(matches) == 2

    # Whitespace flexibility
    text = "Agent said 'I  understand   the    task' clearly."
    matches = _find_pattern_in_text(text, "I understand the task")
    assert len(matches) == 1
    assert text[matches[0][0] : matches[0][1]] == "I  understand   the    task"

    # Edge cases
    assert _find_pattern_in_text("No match here", "missing pattern") == []
    assert _find_pattern_in_text("Some text", "") == []


@pytest.mark.unit
def test_validate_citations_with_valid_range() -> None:
    """Test that valid citation ranges are preserved."""
    agent_run = create_test_agent_run()
    context = LLMContext()
    context.add(agent_run)

    # Valid citation with text range
    text = "The agent [T0B1:<RANGE>I understand</RANGE>] correctly."
    _, citations = resolve_citations_with_context(text, context, validate_text_ranges=True)

    assert len(citations) == 1
    assert citations[0].target.text_range is not None
    assert citations[0].target.text_range.start_pattern == "I understand"


@pytest.mark.unit
def test_validate_citations_with_invalid_range() -> None:
    """Test that invalid citation ranges are removed."""
    agent_run = create_test_agent_run()
    context = LLMContext()
    context.add(agent_run)

    # Invalid citation with non-existent text
    text = "The agent [T0B1:<RANGE>nonexistent text</RANGE>] did something."
    _, citations = resolve_citations_with_context(text, context, validate_text_ranges=True)

    assert len(citations) == 1
    # Text range should be removed because pattern doesn't exist
    assert citations[0].target.text_range is None


@pytest.mark.unit
def test_validate_citations_mixed() -> None:
    """Test validation with mix of valid and invalid ranges."""
    agent_run = create_test_agent_run()
    context = LLMContext()
    context.add(agent_run)

    text = (
        "First [T0B1:<RANGE>I understand</RANGE>] then "
        "[T0B1:<RANGE>nonexistent</RANGE>] and [T0B2]"
    )
    _, citations = resolve_citations_with_context(text, context, validate_text_ranges=True)

    assert len(citations) == 3
    # First citation should keep its range (valid)
    assert citations[0].target.text_range is not None
    assert citations[0].target.text_range.start_pattern == "I understand"
    # Second citation should lose its range (invalid)
    assert citations[1].target.text_range is None
    # Third citation has no range to begin with
    assert citations[2].target.text_range is None


@pytest.mark.unit
def test_validation_disabled() -> None:
    """Test that validation can be disabled."""
    agent_run = create_test_agent_run()
    context = LLMContext()
    context.add(agent_run)

    # Invalid citation but validation disabled
    text = "The agent [T0B1:<RANGE>nonexistent</RANGE>] did something."
    _, citations = resolve_citations_with_context(text, context, validate_text_ranges=False)

    assert len(citations) == 1
    # Text range should be preserved because validation is off
    assert citations[0].target.text_range is not None
    assert citations[0].target.text_range.start_pattern == "nonexistent"


@pytest.mark.unit
def test_validate_citations_without_range() -> None:
    """Test that citations without ranges work normally."""
    agent_run = create_test_agent_run()
    context = LLMContext()
    context.add(agent_run)

    text = "The agent [T0B1] did something [T0B2]."
    _, citations = resolve_citations_with_context(text, context, validate_text_ranges=True)

    assert len(citations) == 2
    assert citations[0].target.text_range is None
    assert citations[1].target.text_range is None
