"""Template formatting utilities for flexible judge prompt configuration.

This module provides utilities for formatting prompt templates with variables
derived from AgentRun objects and placeholders for missing substitutions.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from string import Formatter
from typing import TYPE_CHECKING, Any

from docent.data_models.agent_run import AgentRunView

if TYPE_CHECKING:
    from docent.data_models.agent_run import AgentRun


MISSING_PLACEHOLDER_TEMPLATE = "<<MISSING:{var}>>"


class PlaceholderFormatter(Formatter):
    """Formatter that replaces missing fields with a placeholder."""

    def __init__(self, placeholder_template: str = MISSING_PLACEHOLDER_TEMPLATE) -> None:
        super().__init__()
        self._placeholder_template = placeholder_template

    def _placeholder(self, field_name: str) -> str:
        return self._placeholder_template.format(var=field_name)

    def get_value(self, key: Any, args: Sequence[Any], kwargs: Mapping[str, Any]) -> Any:
        try:
            return super().get_value(key, args, kwargs)
        except (KeyError, IndexError):
            return self._placeholder(str(key))

    def get_field(
        self, field_name: str, args: Sequence[Any], kwargs: Mapping[str, Any]
    ) -> tuple[Any, str]:
        try:
            return super().get_field(field_name, args, kwargs)
        except (KeyError, AttributeError, IndexError):
            return self._placeholder(field_name), field_name


class AgentRunTemplateFormatter:
    """Formats prompt templates with variables derived from AgentRun objects.

    Supports the following template variables:
    - {agent_run} - Full agent run text representation
    - {rubric} - The rubric text
    - {output_schema} - JSON-formatted output schema

    Example:
        formatter = AgentRunTemplateFormatter(
            agent_run=agent_run,
            rubric_text=rubric_text,
            output_schema=output_schema,
        )
        formatted = formatter.format_template("Task: {rubric}")
    """

    # Built-in variables that are recognized in templates
    BUILTIN_VARS = {"agent_run", "rubric", "output_schema"}
    # Required variables that must be present across all templates
    REQUIRED_VARS = {"agent_run", "rubric", "output_schema"}

    def __init__(
        self,
        agent_run: AgentRun,
        rubric_text: str,
        output_schema: dict[str, Any],
        placeholder_template: str = MISSING_PLACEHOLDER_TEMPLATE,
    ) -> None:
        """Initialize the formatter with all context needed for substitution."""
        self._placeholder_template = placeholder_template
        self._context: dict[str, Any] = {
            "agent_run": AgentRunView.from_agent_run(agent_run).to_text(),
            "rubric": rubric_text,
            "output_schema": json.dumps(output_schema, indent=2),
        }

    def format_template(self, template: str) -> str:
        """Format a template string with the given context.

        Missing variables are replaced with a placeholder.
        """
        formatter = PlaceholderFormatter(self._placeholder_template)
        return formatter.vformat(template, (), self._context)

    @staticmethod
    def get_template_variables(template: str) -> set[str]:
        """Extract all variable names from a template string.

        Args:
            template: The template string to parse

        Returns:
            A set of variable names found in the template
        """
        formatter = Formatter()
        return {
            field_name
            for _, field_name, _, _ in formatter.parse(template)
            if field_name is not None
        }

    @staticmethod
    def strip_citation_placeholder(template: str) -> str:
        """Strip {citation_instructions} placeholder and surrounding whitespace from a template.

        This is used for backward compatibility with templates that contain the
        deprecated {citation_instructions} placeholder.

        Args:
            template: The template string to process

        Returns:
            The template with the placeholder and surrounding whitespace removed
        """
        # Remove the placeholder along with surrounding newlines/whitespace
        return re.sub(r"\n*\s*\{citation_instructions\}\s*\n*", "", template)

    @staticmethod
    def validate_template_variables(
        templates: list[str],
        allowed_unknown: set[str] | None = None,
    ) -> None:
        """Validate template variables across all templates.

        Checks that:
        1. No unknown variables exist (only BUILTIN_VARS and allowed_unknown are permitted)
        2. All BUILTIN_VARS are present across the templates collectively

        Args:
            templates: List of template strings to validate
            allowed_unknown: Additional variables to allow beyond BUILTIN_VARS (default: None)

        Raises:
            ValueError: If unknown variables exist or required variables are missing
        """
        all_variables: set[str] = set()
        for template in templates:
            all_variables |= AgentRunTemplateFormatter.get_template_variables(template)

        # Check for unknown variables
        allowed = AgentRunTemplateFormatter.BUILTIN_VARS
        if allowed_unknown:
            allowed = allowed | allowed_unknown
        unknown_vars = all_variables - allowed
        if unknown_vars:
            raise ValueError(
                f"Unknown template variable(s): {unknown_vars}. "
                f"Must be one of {AgentRunTemplateFormatter.BUILTIN_VARS}."
            )

        # Check for missing required variables
        missing_vars = AgentRunTemplateFormatter.REQUIRED_VARS - all_variables
        if missing_vars:
            raise ValueError(
                f"Missing required template variable(s): {missing_vars}. "
                f"Templates must collectively contain all of {AgentRunTemplateFormatter.REQUIRED_VARS}."
            )
