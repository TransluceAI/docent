"""Unit tests for Rubric.materialize_messages() and related validation."""

from typing import Any

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, SystemMessage, UserMessage
from docent.data_models.transcript import Transcript
from docent.judges.types import (
    DEFAULT_JUDGE_OUTPUT_SCHEMA,
    DEFAULT_JUDGE_SYSTEM_PROMPT_TEMPLATE,
    JUDGE_CITATION_INSTRUCTIONS,
    OutputParsingMode,
    PromptTemplateMessage,
    Rubric,
)


@pytest.fixture
def sample_transcript() -> Transcript:
    return Transcript(
        id="transcript-123",
        messages=[
            UserMessage(content="Hello"),
            AssistantMessage(content="Hi there"),
        ],
    )


@pytest.fixture
def sample_agent_run(sample_transcript: Transcript) -> AgentRun:
    return AgentRun(
        id="agent-run-456",
        transcripts=[sample_transcript],
    )


@pytest.fixture
def schema_without_citations() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
        },
        "required": ["label"],
    }


@pytest.fixture
def schema_with_citations() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "explanation": {"type": "string", "citations": True},
        },
        "required": ["label", "explanation"],
    }


class TestRubricMaterializeMessagesDefaultTemplates:
    """Tests for the default prompt_templates configuration."""

    @pytest.mark.unit
    def test_returns_user_message_when_using_default_prompt_templates(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert len(messages) == 1
        assert isinstance(messages[0], UserMessage)

    @pytest.mark.unit
    def test_formats_rubric_text_in_output(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="My specific rubric text",
            output_schema=schema_without_citations,
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert "My specific rubric text" in messages[0].content

    @pytest.mark.unit
    def test_formats_agent_run_in_output(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
        )
        messages = rubric.materialize_messages(sample_agent_run)

        # Agent run content should be present (transcript messages)
        assert "Hello" in messages[0].content or "Hi there" in messages[0].content

    @pytest.mark.unit
    def test_default_prompt_template_has_no_citation_placeholder(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(rubric_text="Test rubric", output_schema=schema_without_citations)
        messages = rubric.materialize_messages(sample_agent_run)
        assert "{citation_instructions}" not in messages[0].content

    @pytest.mark.unit
    def test_appends_citation_instructions_when_schema_requests_citations(
        self, sample_agent_run: AgentRun, schema_with_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_with_citations,
        )
        messages = rubric.materialize_messages(sample_agent_run)

        # Citation instructions should be appended
        content = messages[0].content
        assert isinstance(content, str)
        assert JUDGE_CITATION_INSTRUCTIONS in content

    @pytest.mark.unit
    def test_no_citation_instructions_when_schema_does_not_request(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
        )
        messages = rubric.materialize_messages(sample_agent_run)

        # Should not have citation instructions about citing sources
        # The word "citations" might appear in schema but not as instructions
        content = messages[0].content
        assert "For strings which require citations" not in content


class TestRubricMaterializeMessagesFlexibleSystem:
    """Tests for the new flexible prompt_templates system."""

    @pytest.mark.unit
    def test_handles_system_role(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(
                    role="system", content="System: {rubric} {agent_run} {output_schema}"
                ),
            ],
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert len(messages) == 1
        assert isinstance(messages[0], SystemMessage)

    @pytest.mark.unit
    def test_handles_user_role(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(
                    role="user", content="User: {rubric} {agent_run} {output_schema}"
                ),
            ],
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert len(messages) == 1
        assert isinstance(messages[0], UserMessage)

    @pytest.mark.unit
    def test_handles_assistant_role(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(
                    role="system", content="System: {rubric} {agent_run} {output_schema}"
                ),
                PromptTemplateMessage(role="assistant", content="I understand."),
            ],
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert len(messages) == 2
        assert isinstance(messages[1], AssistantMessage)
        assert messages[1].content == "I understand."

    @pytest.mark.unit
    def test_multiple_messages_in_order(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_without_citations,
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(role="system", content="System content {rubric} {agent_run}"),
                PromptTemplateMessage(role="user", content="User content {output_schema}"),
                PromptTemplateMessage(role="assistant", content="Assistant content"),
            ],
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert len(messages) == 3
        assert isinstance(messages[0], SystemMessage)
        assert isinstance(messages[1], UserMessage)
        assert isinstance(messages[2], AssistantMessage)

    @pytest.mark.unit
    def test_formats_each_template(
        self, sample_agent_run: AgentRun, schema_without_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="My rubric",
            output_schema=schema_without_citations,
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(
                    role="system", content="Rubric: {rubric}, Agent: {agent_run}"
                ),
                PromptTemplateMessage(role="user", content="Schema: {output_schema}"),
            ],
        )
        messages = rubric.materialize_messages(sample_agent_run)

        assert "My rubric" in messages[0].content
        # Agent run content should be in first message
        assert "Hello" in messages[0].content or "Hi there" in messages[0].content

    @pytest.mark.unit
    def test_appends_citations_to_last_message_only(
        self, sample_agent_run: AgentRun, schema_with_citations: dict[str, Any]
    ):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_schema=schema_with_citations,
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(role="system", content="System: {rubric} {agent_run}"),
                PromptTemplateMessage(role="user", content="User: {output_schema}"),
            ],
        )
        messages = rubric.materialize_messages(sample_agent_run)

        # First message should NOT have citation instructions
        first_content = messages[0].content
        assert isinstance(first_content, str)
        assert "For strings which require citations" not in first_content
        # Last message should have citation instructions
        last_content = messages[1].content
        assert isinstance(last_content, str)
        assert JUDGE_CITATION_INSTRUCTIONS in last_content


class TestRubricValidation:
    """Tests for Rubric field validators."""

    @pytest.mark.unit
    def test_rejects_unknown_variable_in_prompt_templates(self):
        with pytest.raises(ValueError, match="Unknown template variable"):
            Rubric(
                rubric_text="Test rubric",
                prompt_templates=[
                    PromptTemplateMessage(
                        role="user",
                        content="{agent_run} {rubric} {output_schema} {unknown_var}",
                    ),
                ],
            )

    @pytest.mark.unit
    def test_rejects_missing_required_variable_in_prompt_templates(self):
        with pytest.raises(ValueError, match="Missing required template variable"):
            Rubric(
                rubric_text="Test rubric",
                prompt_templates=[
                    PromptTemplateMessage(
                        role="user",
                        content="{agent_run}",  # Missing rubric and output_schema
                    ),
                ],
            )

    @pytest.mark.unit
    def test_accepts_valid_prompt_templates(self):
        rubric = Rubric(
            rubric_text="Test rubric",
            output_parsing_mode=OutputParsingMode.CONSTRAINED_DECODING,
            prompt_templates=[
                PromptTemplateMessage(
                    role="user",
                    content="{agent_run} {rubric} {output_schema}",
                ),
            ],
        )
        assert rubric.prompt_templates is not None
        assert len(rubric.prompt_templates) == 1

    @pytest.mark.unit
    def test_xml_key_validation_passes_with_tag(self):
        # Should not raise
        rubric = Rubric(
            rubric_text="Test rubric",
            output_parsing_mode=OutputParsingMode.XML_KEY,
            response_xml_key="response",
            prompt_templates=[
                PromptTemplateMessage(
                    role="user",
                    content="{rubric} {agent_run} {output_schema} <response>...</response>",
                )
            ],
        )
        assert rubric.response_xml_key == "response"

    @pytest.mark.unit
    def test_xml_key_validation_checks_prompt_templates(self):
        # Should not raise if tag is in prompt_templates
        rubric = Rubric(
            rubric_text="Test rubric",
            output_parsing_mode=OutputParsingMode.XML_KEY,
            response_xml_key="answer",
            prompt_templates=[
                PromptTemplateMessage(
                    role="user",
                    content="{rubric} {agent_run} {output_schema} <answer>...</answer>",
                ),
            ],
        )
        assert rubric.response_xml_key == "answer"

    @pytest.mark.unit
    def test_default_prompt_templates_is_valid(self):
        # The default templates should pass validation
        rubric = Rubric(rubric_text="Test rubric")
        assert rubric.prompt_templates[0].content == DEFAULT_JUDGE_SYSTEM_PROMPT_TEMPLATE

    @pytest.mark.unit
    def test_default_output_schema_is_valid(self):
        rubric = Rubric(rubric_text="Test rubric")
        assert rubric.output_schema == DEFAULT_JUDGE_OUTPUT_SCHEMA
