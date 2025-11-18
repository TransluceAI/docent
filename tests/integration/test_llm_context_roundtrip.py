"""Integration tests for LLMContext serialization round-trip."""

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, UserMessage
from docent.data_models.citation import TranscriptBlockContentItem
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.data_models.transcript import Transcript
from docent.sdk.llm_context import LLMContext
from docent_core.docent.db.schemas.auth_models import User
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.utils.llm_context import deserialize_llm_context


@pytest.mark.integration
async def test_plain_agent_run_roundtrip(
    mono_service: MonoService, test_collection_id: str, test_user: User
) -> None:
    """Test that plain AgentRun can be serialized and deserialized."""
    transcript = Transcript(
        messages=[
            UserMessage(content="Hello"),
            AssistantMessage(content="Hi there"),
        ],
        metadata={"key": "value"},
    )
    agent_run = AgentRun(
        transcripts=[transcript],
        metadata={"task": "test"},
    )

    # Store in DB
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=[agent_run])

    # Create context and serialize
    context = LLMContext()
    context.add(agent_run)

    original_str = context.to_str()
    original_citation = context.resolve_item_alias("T0B0")
    assert isinstance(original_citation, TranscriptBlockContentItem)

    serialized = context.to_dict()

    # Deserialize
    restored_context = await deserialize_llm_context(serialized, mono_service)

    # Verify behavior preserved
    assert restored_context.to_str() == original_str
    restored_citation = restored_context.resolve_item_alias("T0B0")
    assert isinstance(restored_citation, TranscriptBlockContentItem)
    assert restored_citation.agent_run_id == original_citation.agent_run_id
    assert restored_citation.transcript_id == original_citation.transcript_id
    assert restored_citation.block_idx == original_citation.block_idx


@pytest.mark.integration
async def test_formatted_agent_run_roundtrip(mono_service: MonoService) -> None:
    """Test that FormattedAgentRun preserves customizations through round-trip."""
    msg0 = UserMessage(content="Message 0")
    msg1 = AssistantMessage(content="Message 1")
    msg2 = UserMessage(content="Message 2")

    transcript = Transcript(messages=[msg0, msg1, msg2], metadata={})
    formatted_transcript = FormattedTranscript.from_transcript(transcript)

    # Remove middle message to test id_to_original_index preservation
    msg2_id = formatted_transcript.messages[2].id
    assert msg2_id is not None
    formatted_transcript.messages = [
        formatted_transcript.messages[0],
        formatted_transcript.messages[2],
    ]

    agent_run = AgentRun(transcripts=[transcript], metadata={})
    formatted_agent_run = FormattedAgentRun(
        id=agent_run.id,
        name=agent_run.name,
        description=agent_run.description,
        transcripts=[formatted_transcript],
        transcript_groups=agent_run.transcript_groups,
        metadata=agent_run.metadata,
    )

    # Create context and serialize
    context = LLMContext()
    context.add(formatted_agent_run)

    # Message 1 should be absent, message 2 should still be T0B2 (not T0B1)
    original_str = context.to_str()
    assert "T0B0" in original_str
    assert "T0B1" not in original_str
    assert "T0B2" in original_str

    serialized = context.to_dict()

    # Deserialize
    restored_context = await deserialize_llm_context(serialized, mono_service)

    # Verify customizations preserved
    restored_str = restored_context.to_str()
    assert restored_str == original_str
    assert "T0B0" in restored_str
    assert "T0B1" not in restored_str
    assert "T0B2" in restored_str

    # Verify id_to_original_index preserved
    restored_formatted_run = restored_context.agent_run_aliases[0]
    assert isinstance(restored_formatted_run, FormattedAgentRun)
    restored_formatted_transcript = restored_formatted_run.transcripts[0]
    assert restored_formatted_transcript.id_to_original_index[msg2_id] == 2


@pytest.mark.integration
async def test_mixed_context_roundtrip(
    mono_service: MonoService, test_collection_id: str, test_user: User
) -> None:
    """Test round-trip with mix of plain and formatted objects."""
    plain_transcript = Transcript(
        messages=[UserMessage(content="Plain")],
        metadata={},
    )

    formatted_messages = [
        UserMessage(content="Formatted 1"),
        AssistantMessage(content="Formatted 2"),
    ]
    formatted_transcript = FormattedTranscript.from_transcript(
        Transcript(messages=formatted_messages, metadata={})
    )

    plain_agent_run = AgentRun(
        transcripts=[plain_transcript],
        metadata={},
    )

    # Store plain agent run in DB
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=[plain_agent_run])

    # Create context with both
    context = LLMContext()
    context.add(formatted_transcript)
    context.add(plain_agent_run)

    original_str = context.to_str()
    serialized = context.to_dict()

    # Deserialize
    restored_context = await deserialize_llm_context(serialized, mono_service)

    # Verify behavior preserved
    assert restored_context.to_str() == original_str


@pytest.mark.integration
async def test_formatted_agent_run_does_not_fetch_embedded_transcripts(
    mono_service: MonoService,
) -> None:
    """Regression test: embedded transcripts in FormattedAgentRun should not be fetched from DB.

    When a FormattedAgentRun is serialized, its transcripts are embedded in the data.
    During deserialization, we should NOT fetch these transcripts from the database.
    """
    from unittest.mock import AsyncMock, patch

    # Create formatted agent run with transcripts
    t1 = Transcript(id="t1", messages=[UserMessage(content="Test 1")], metadata={})
    t2 = Transcript(id="t2", messages=[UserMessage(content="Test 2")], metadata={})

    agent_run = AgentRun(id="test-run", transcripts=[t1, t2], metadata={})
    formatted_agent_run = FormattedAgentRun.from_agent_run(agent_run)

    # Serialize
    context = LLMContext()
    context.add(formatted_agent_run)
    serialized = context.to_dict()

    # Mock the transcript fetching to ensure it's NOT called
    with patch.object(
        mono_service, "get_transcripts_by_ids", new_callable=AsyncMock
    ) as mock_get_transcripts:
        mock_get_transcripts.return_value = []

        # Deserialize
        await deserialize_llm_context(serialized, mono_service)

        # Critical assertion: transcripts should NOT be fetched since they're embedded
        mock_get_transcripts.assert_not_called()


@pytest.mark.integration
async def test_citation_stability_after_serialization(
    mono_service: MonoService, test_collection_id: str, test_user: User
) -> None:
    """Test that citations remain stable through serialization/deserialization.

    This verifies the core fix: serialized aliases are authoritative, so citations
    remain valid even if the underlying data changes after serialization.
    """
    # Create agent run with 3 transcripts
    t1 = Transcript(id="t1", messages=[UserMessage(content="Transcript 1")], metadata={})
    t2 = Transcript(id="t2", messages=[UserMessage(content="Transcript 2")], metadata={})
    t3 = Transcript(id="t3", messages=[UserMessage(content="Transcript 3")], metadata={})

    agent_run = AgentRun(
        id="test-run",
        transcripts=[t1, t2, t3],
        metadata={},
    )

    # Store in DB
    ctx = await mono_service.get_default_view_ctx(test_collection_id, test_user)
    await mono_service.add_agent_runs(ctx=ctx, agent_runs=[agent_run])

    # Create context and serialize
    context = LLMContext()
    context.add(agent_run)

    # Test citations before serialization
    original_citations: dict[int, str] = {}
    for idx in range(3):
        citation = context.resolve_item_alias(f"T{idx}B0")
        assert isinstance(citation, TranscriptBlockContentItem)
        original_citations[idx] = citation.transcript_id

    # Verify all three transcripts present
    assert len(original_citations) == 3
    assert set(original_citations.values()) == {"t1", "t2", "t3"}

    # Serialize and deserialize
    serialized = context.to_dict()
    restored_context = await deserialize_llm_context(serialized, mono_service)

    # Critical test: citations should resolve to the same transcripts
    # This verifies the core fix - aliases are stable through serialization
    for idx in range(3):
        restored_citation = restored_context.resolve_item_alias(f"T{idx}B0")
        assert isinstance(restored_citation, TranscriptBlockContentItem)
        assert restored_citation.transcript_id == original_citations[idx]
