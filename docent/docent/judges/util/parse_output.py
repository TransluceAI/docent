from typing import Any, cast

import jsonschema

from docent._llm_util.data_models.exceptions import ValidationFailedException
from docent.judges.util.forgiving_json import forgiving_json_loads


def parse_and_validate_output_str(output_str: str, output_schema: dict[str, Any]) -> dict[str, Any]:
    """Parse and validate LLM output against a JSON schema with forgiving parsing.

    Args:
        output_str: The LLM output string to parse
        output_schema: The JSON schema to validate against

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
            f"Expected dict output, got {type(output).__name__}",
            failed_output=output_str,
        )

    output_dict = cast(dict[str, Any], output)
    try:
        jsonschema.validate(output_dict, output_schema)
    except jsonschema.ValidationError as e:
        raise ValidationFailedException(
            f"Schema validation failed: {e.message}",
            failed_output=output_str,
        )

    return output_dict
