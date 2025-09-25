import json
import re
from typing import Any


def extract_json_from_response(full_content: str) -> dict[str, Any] | list[Any]:
    """
    Extracts the JSON from a response string.

    The response should contain a JSON code block, such as the following:

    ```json
    {
        "name": "Counterfactual 1",
        "description": "This is a counterfactual description."
    }
    ```

    Returns the JSON as a dictionary or list.
    """
    # Use regex to find all code blocks (```json or plain ```)
    # This pattern matches code blocks and captures their content
    # Allow optional whitespace around the markers
    pattern = r"```(?:json)?\s*(.*?)\s*```"
    matches = re.findall(pattern, full_content, re.DOTALL)

    if not matches:
        raise ValueError("No JSON block found in the response")

    # Get the last match (as per the requirement to use the last block)
    json_str = matches[-1].strip()

    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse JSON: {e}")
