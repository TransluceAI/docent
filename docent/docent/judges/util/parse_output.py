from typing import Any, cast

import jsonschema

from docent._llm_util.data_models.exceptions import ValidationFailedException
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.remove_invalid_citation_ranges import remove_invalid_citation_ranges
from docent.judges.types import traverse_schema_and_transform
from docent.judges.util.forgiving_json import forgiving_json_loads

logger = get_logger(__name__)


def _validate_rubric_output(
    output: dict[str, Any], output_schema: dict[str, Any], agent_run: AgentRun
) -> dict[str, Any]:
    """Validate and filter citation text ranges in rubric results.
    Also check that the output conforms to the output schema.

    Args:
        output: Raw results from LLM judge
        agent_run: Agent run containing transcript data for validation

    Returns:
        Validated result dict with invalid citations removed

    Raises:
        ValidationFailedException: If validation fails
    """

    def _validate_citation_string(text: str) -> str:
        validated_text = remove_invalid_citation_ranges(text, agent_run)
        if validated_text != text:
            logger.warning(
                f"Citation validation removed invalid text range from citation in judge result. "
                f"Agent run ID: {agent_run.id}, "
                f"Original text: {text}, "
                f"Validated text: {validated_text}, "
            )
        return validated_text

    try:
        jsonschema.validate(output, output_schema)
    except jsonschema.ValidationError as e:
        raise ValidationFailedException(f"Schema validation failed: {e}", failed_output=str(output))

    try:
        return traverse_schema_and_transform(output, output_schema, _validate_citation_string)
    except Exception as e:
        raise ValidationFailedException(
            f"Citation validation failed: {e}", failed_output=str(output)
        )


def parse_and_validate_output_str(
    output_str: str, output_schema: dict[str, Any], agent_run: AgentRun
) -> dict[str, Any]:
    """Parse and validate LLM output for rubric evaluation.

    Args:
        llm_output: The LLM output to parse
        output_schema: The schema to validate against
        agent_run: Agent run for citation validation

    Returns:
        Validated output dict

    Raises:
        ValidationFailedException: If parsing or validation fails
    """

    try:
        output = forgiving_json_loads(output_str)
    except Exception as e:
        raise ValidationFailedException(
            f"Failed to parse JSON: {e}. Raw text: `{output_str}`",
            failed_output=output_str,
        )

    if not isinstance(output, dict):
        raise ValidationFailedException(
            f"Expected dict output, got {type(output)}. Raw text: {output_str}",
            failed_output=output_str,
        )

    return _validate_rubric_output(cast(dict[str, Any], output), output_schema, agent_run)
