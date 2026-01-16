"""Unit tests for AgentRunTemplateFormatter and related utilities."""

import pytest

from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import AssistantMessage, UserMessage
from docent.data_models.transcript import Transcript
from docent.judges.util.template_formatter import (
    AgentRunTemplateFormatter,
    PlaceholderFormatter,
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


class TestPlaceholderFormatter:
    @pytest.mark.unit
    def test_formats_known_variables(self):
        formatter = PlaceholderFormatter()
        result = formatter.format("{name} is {age}", name="Alice", age=30)
        assert result == "Alice is 30"

    @pytest.mark.unit
    def test_replaces_missing_variables_with_placeholder(self):
        formatter = PlaceholderFormatter()
        result = formatter.format("{name} is {unknown}")
        assert result == "<<MISSING:name>> is <<MISSING:unknown>>"

    @pytest.mark.unit
    def test_custom_placeholder_template(self):
        formatter = PlaceholderFormatter(placeholder_template="[UNKNOWN:{var}]")
        result = formatter.format("{missing}")
        assert result == "[UNKNOWN:missing]"


class TestGetTemplateVariables:
    @pytest.mark.unit
    def test_extracts_single_variable(self):
        variables = AgentRunTemplateFormatter.get_template_variables("{rubric}")
        assert variables == {"rubric"}

    @pytest.mark.unit
    def test_extracts_multiple_variables(self):
        variables = AgentRunTemplateFormatter.get_template_variables(
            "{agent_run} and {rubric} with {output_schema}"
        )
        assert variables == {"agent_run", "rubric", "output_schema"}

    @pytest.mark.unit
    def test_empty_template_returns_empty_set(self):
        variables = AgentRunTemplateFormatter.get_template_variables("")
        assert variables == set()

    @pytest.mark.unit
    def test_template_without_variables_returns_empty_set(self):
        variables = AgentRunTemplateFormatter.get_template_variables("plain text")
        assert variables == set()

    @pytest.mark.unit
    def test_escaped_braces_not_extracted(self):
        variables = AgentRunTemplateFormatter.get_template_variables("{{escaped}}")
        assert variables == set()

    @pytest.mark.unit
    def test_mixed_escaped_and_real_variables(self):
        variables = AgentRunTemplateFormatter.get_template_variables("{{escaped}} and {real}")
        assert variables == {"real"}


class TestFormatTemplate:
    @pytest.mark.unit
    def test_formats_all_builtin_variables(self, sample_agent_run: AgentRun):
        formatter = AgentRunTemplateFormatter(
            agent_run=sample_agent_run,
            rubric_text="Test rubric",
            output_schema={"type": "object"},
        )
        template = "Rubric: {rubric}\nSchema: {output_schema}\nRun: {agent_run}"
        result = formatter.format_template(template)

        assert "Test rubric" in result
        assert '"type": "object"' in result
        assert "agent-run-456" in result or "Hello" in result

    @pytest.mark.unit
    def test_replaces_unknown_variable_with_placeholder(self, sample_agent_run: AgentRun):
        formatter = AgentRunTemplateFormatter(
            agent_run=sample_agent_run,
            rubric_text="Test rubric",
            output_schema={"type": "object"},
        )
        template = "{rubric} with {unknown_var}"
        result = formatter.format_template(template)

        assert "Test rubric" in result
        assert "<<MISSING:unknown_var>>" in result

    @pytest.mark.unit
    def test_preserves_literal_text(self, sample_agent_run: AgentRun):
        formatter = AgentRunTemplateFormatter(
            agent_run=sample_agent_run,
            rubric_text="Test rubric",
            output_schema={"type": "object"},
        )
        template = "Prefix: {rubric} :Suffix"
        result = formatter.format_template(template)

        assert result.startswith("Prefix:")
        assert result.endswith(":Suffix")


class TestStripCitationPlaceholder:
    @pytest.mark.unit
    def test_removes_citation_placeholder(self):
        template = "Before\n\n{citation_instructions}\n\nAfter"
        result = AgentRunTemplateFormatter.strip_citation_placeholder(template)
        assert "{citation_instructions}" not in result
        assert "Before" in result
        assert "After" in result

    @pytest.mark.unit
    def test_handles_template_without_placeholder(self):
        template = "No placeholder here"
        result = AgentRunTemplateFormatter.strip_citation_placeholder(template)
        assert result == "No placeholder here"

    @pytest.mark.unit
    def test_removes_surrounding_whitespace(self):
        template = "Start   {citation_instructions}   End"
        result = AgentRunTemplateFormatter.strip_citation_placeholder(template)
        assert "{citation_instructions}" not in result
        # Should have removed the whitespace around the placeholder
        assert result == "StartEnd"

    @pytest.mark.unit
    def test_handles_placeholder_at_end(self):
        template = "Content\n{citation_instructions}"
        result = AgentRunTemplateFormatter.strip_citation_placeholder(template)
        assert "{citation_instructions}" not in result
        assert "Content" in result


class TestValidateTemplateVariables:
    @pytest.mark.unit
    def test_accepts_all_required_variables(self):
        templates = ["{agent_run}", "{rubric}", "{output_schema}"]
        # Should not raise
        AgentRunTemplateFormatter.validate_template_variables(templates)

    @pytest.mark.unit
    def test_accepts_variables_in_single_template(self):
        templates = ["{agent_run} {rubric} {output_schema}"]
        # Should not raise
        AgentRunTemplateFormatter.validate_template_variables(templates)

    @pytest.mark.unit
    def test_rejects_unknown_variable(self):
        templates = ["{agent_run} {rubric} {output_schema} {unknown_var}"]
        with pytest.raises(ValueError, match="Unknown template variable"):
            AgentRunTemplateFormatter.validate_template_variables(templates)

    @pytest.mark.unit
    def test_rejects_missing_required_variable(self):
        templates = ["{agent_run}"]  # Missing rubric and output_schema
        with pytest.raises(ValueError, match="Missing required template variable"):
            AgentRunTemplateFormatter.validate_template_variables(templates)

    @pytest.mark.unit
    def test_accepts_allowed_unknown_variable(self):
        templates = ["{agent_run} {rubric} {output_schema} {citation_instructions}"]
        # Should not raise when citation_instructions is allowed
        AgentRunTemplateFormatter.validate_template_variables(
            templates, allowed_unknown={"citation_instructions"}
        )

    @pytest.mark.unit
    def test_rejects_unknown_not_in_allowed(self):
        templates = ["{agent_run} {rubric} {output_schema} {other_var}"]
        with pytest.raises(ValueError, match="Unknown template variable"):
            AgentRunTemplateFormatter.validate_template_variables(
                templates, allowed_unknown={"citation_instructions"}
            )

    @pytest.mark.unit
    def test_variables_spread_across_templates(self):
        templates = ["{agent_run}", "{rubric}", "{output_schema}"]
        # Should not raise - all required vars present across templates
        AgentRunTemplateFormatter.validate_template_variables(templates)

    @pytest.mark.unit
    def test_error_message_includes_unknown_vars(self):
        templates = ["{agent_run} {rubric} {output_schema} {foo} {bar}"]
        with pytest.raises(ValueError) as exc_info:
            AgentRunTemplateFormatter.validate_template_variables(templates)
        error_message = str(exc_info.value)
        assert "foo" in error_message or "bar" in error_message

    @pytest.mark.unit
    def test_error_message_includes_missing_vars(self):
        templates = ["{agent_run}"]
        with pytest.raises(ValueError) as exc_info:
            AgentRunTemplateFormatter.validate_template_variables(templates)
        error_message = str(exc_info.value)
        assert "rubric" in error_message or "output_schema" in error_message
