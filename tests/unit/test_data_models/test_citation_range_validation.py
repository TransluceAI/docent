"""Unit tests for citation range validation functionality."""

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import AssistantMessage, UserMessage
from docent.data_models.remove_invalid_citation_ranges import (
    find_citation_matches_in_text,
    remove_invalid_citation_ranges,
)
from docent.data_models.transcript import Transcript


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
        transcripts={"0": transcript},
        transcript_groups={},
    )


class TestCitationMatching:
    """Test regex helpers and citation matching."""

    @pytest.mark.unit
    def test_citation_matching_scenarios(self):
        """Test various citation matching scenarios."""
        # Basic matching
        text = "The agent said I understand the task and continued."
        matches = find_citation_matches_in_text(text, "I understand the task")
        assert len(matches) == 1
        assert text[matches[0][0] : matches[0][1]] == "I understand the task"

        # Multiple matches
        text = "First: I understand. Second: I understand again."
        matches = find_citation_matches_in_text(text, "I understand")
        assert len(matches) == 2

        # Whitespace flexibility
        text = "Agent said 'I  understand   the    task' clearly."
        matches = find_citation_matches_in_text(text, "I understand the task")
        assert len(matches) == 1
        assert text[matches[0][0] : matches[0][1]] == "I  understand   the    task"

        # Edge cases
        assert find_citation_matches_in_text("No match here", "missing pattern") == []
        assert find_citation_matches_in_text("Some text", "") == []  # Empty pattern


class TestTextCleaning:
    """Test text cleaning functionality."""

    @pytest.mark.unit
    def test_validate_and_clean_citations_scenarios(
        self,
    ):
        """Test citation validation and cleaning in a single pass."""
        agent_run = create_test_agent_run()

        valid_range_citation = "[T0B1:<RANGE>I understand</RANGE>]"
        invalid_range_citation = "[T0B1:<RANGE>nonexistent</RANGE>]"
        block_citation = "[T0B1]"

        citing_text = valid_range_citation + invalid_range_citation + block_citation

        cleaned_text = remove_invalid_citation_ranges(citing_text, agent_run)

        assert cleaned_text == "[T0B1:<RANGE>I understand</RANGE>][T0B1][T0B1]"
