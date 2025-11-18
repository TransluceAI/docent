from typing import Any, cast

import jsonschema

from docent._llm_util.data_models.exceptions import ValidationFailedException
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.judges.util.forgiving_json import forgiving_json_loads

logger = get_logger(__name__)


def _validate_rubric_output(
    output: dict[str, Any], output_schema: dict[str, Any], agent_run: AgentRun
) -> dict[str, Any]:
    """Validate that the output conforms to the output schema.

    Args:
        output: Raw results from LLM judge
        agent_run: Agent run (unused, kept for backwards compatibility)
        output_schema: Schema to validate against

    Returns:
        Validated result dict

    Raises:
        ValidationFailedException: If validation fails
    """
    try:
        jsonschema.validate(output, output_schema)
    except jsonschema.ValidationError as e:
        raise ValidationFailedException(f"Schema validation failed: {e}", failed_output=str(output))

    return output


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
