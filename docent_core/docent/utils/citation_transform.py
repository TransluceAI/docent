"""Transform structured output with citation fields into chat-compatible format.

When result set outputs have nested {text, citations} objects (from schemas with
`"citations": true`), this module transforms them into a format suitable for chat
messages: a single JSON string with all citations adjusted to point to the correct
positions in that string.
"""

import json
from typing import Any, cast


def build_escape_mapping(text: str) -> list[int]:
    """Map original text positions to positions in JSON-escaped string.

    For each character position in the original text, returns the corresponding
    position in the JSON-escaped version (without surrounding quotes).

    Example:
        text = 'say "hi"'
        escaped = 'say \\"hi\\"'  (what json.dumps produces inside quotes)
        mapping = [0, 1, 2, 3, 4, 6, 8, 10, 12]
        # Position 4 (the first ") maps to position 4 in escaped (start of \\")
        # Position 5 (h) maps to position 6 (after the \\")
    """
    mapping: list[int] = []
    escaped_idx = 0
    for char in text:
        mapping.append(escaped_idx)
        # Get the escaped representation of this single character
        escaped_char = json.dumps(char)[1:-1]  # Remove surrounding quotes
        escaped_idx += len(escaped_char)
    mapping.append(escaped_idx)  # End position for slicing
    return mapping


def transform_output_for_chat(
    output: dict[str, Any],
) -> tuple[str, list[dict[str, Any]]]:
    """Transform structured output with citation fields into chat format.

    Takes an output dict that may contain nested {text, citations} objects
    (created by the citation resolver for schema fields with "citations": true)
    and transforms it into:
    1. A JSON string with {text, citations} replaced by just the text
    2. A list of citations with start_idx/end_idx adjusted to point to
       the correct positions in the JSON string

    Args:
        output: The result output dict, potentially containing nested
            {"text": "...", "citations": [...]} objects.

    Returns:
        Tuple of (json_string, adjusted_citations) where:
        - json_string is the output formatted as JSON with citation objects
          replaced by their text values
        - adjusted_citations is a list of citation dicts with start_idx and
          end_idx adjusted to point to positions in json_string

    Example:
        Input:
            {
                "category": "helpful",
                "reasoning": {
                    "text": "The agent did X",
                    "citations": [{"start_idx": 14, "end_idx": 15, ...}]
                }
            }
        Output:
            (
                '{\\n  "category": "helpful",\\n  "reasoning": "The agent did X"\\n}',
                [{"start_idx": 52, "end_idx": 53, ...}]  # Adjusted to JSON position
            )
    """
    # Collect all citation fields we find during transformation
    collected: list[tuple[str, list[dict[str, Any]]]] = []

    def replace_citation_fields(obj: Any) -> Any:
        """Recursively replace {text, citations} objects with just the text."""
        if isinstance(obj, dict):
            obj_dict = cast(dict[str, Any], obj)
            # Check if this is a citation field: exactly {text: str, citations: list}
            if (
                set(obj_dict.keys()) == {"text", "citations"}
                and isinstance(obj_dict.get("text"), str)
                and isinstance(obj_dict.get("citations"), list)
            ):
                text_val = cast(str, obj_dict["text"])
                citations_val = cast(list[dict[str, Any]], obj_dict["citations"])
                collected.append((text_val, citations_val))
                return text_val
            # Otherwise recurse into dict values
            return {k: replace_citation_fields(v) for k, v in obj_dict.items()}
        elif isinstance(obj, list):
            return [replace_citation_fields(item) for item in cast(list[Any], obj)]
        else:
            return obj

    # Transform the output, collecting citation fields
    simplified = replace_citation_fields(output)

    # Stringify with consistent formatting
    json_str = json.dumps(simplified, indent=2, ensure_ascii=False)

    # For each collected text, find it in the JSON and adjust citations
    adjusted_citations: list[dict[str, Any]] = []
    used_positions: set[int] = set()  # Track positions to handle duplicates

    for text, citations in collected:
        if not citations:
            continue

        # Find where this text appears in the JSON string
        # json.dumps(text) gives us "escaped text" with quotes
        escaped_with_quotes = json.dumps(text, ensure_ascii=False)

        # Find all occurrences and pick one we haven't used
        search_start = 0
        pos = -1
        while True:
            found_pos = json_str.find(escaped_with_quotes, search_start)
            if found_pos == -1:
                break
            if found_pos not in used_positions:
                pos = found_pos
                used_positions.add(pos)
                break
            search_start = found_pos + 1

        if pos == -1:
            # Text not found in JSON string - skip these citations
            continue

        # Position where the actual text content starts (after opening quote)
        text_start = pos + 1

        # Build mapping from original positions to escaped positions
        escape_map = build_escape_mapping(text)

        # Adjust each citation's indices
        for cite in citations:
            original_start: int = cite.get("start_idx") or 0
            original_end: int = cite.get("end_idx") or 0

            # Map through the escape mapping, clamping to valid range
            escaped_start: int = escape_map[min(original_start, len(escape_map) - 1)]
            escaped_end: int = escape_map[min(original_end, len(escape_map) - 1)]

            adjusted_cite: dict[str, Any] = {
                **cite,
                "start_idx": text_start + escaped_start,
                "end_idx": text_start + escaped_end,
            }
            adjusted_citations.append(adjusted_cite)

    return json_str, adjusted_citations
