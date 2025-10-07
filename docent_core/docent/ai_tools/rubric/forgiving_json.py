import json
import re
from typing import Any


def _repair_json(text: str) -> str:
    """Strip leading/trailing text and fix unescaped quotes/newlines."""

    json_start = None
    for i, char in enumerate(text):
        remaining = text[i:]
        if (
            char in '[{"'
            or char.isdigit()
            or char == "-"
            or remaining.startswith("null")
            or remaining.startswith("true")
            or remaining.startswith("false")
        ):
            json_start = i
            break
    if json_start is None:
        raise ValueError("No valid JSON start found")

    result: list[str] = []
    in_string = False
    escape_next = False
    depth = 0
    started_with_container = text[json_start] in "[{"

    for i in range(json_start, len(text)):
        char = text[i]

        if escape_next:
            result.append(char)
            escape_next = False
            continue

        if char == "\\":
            result.append(char)
            escape_next = True
            continue

        if char == '"':
            if in_string:
                # Check if quote should be escaped by looking at what follows
                remaining = text[i + 1 :].lstrip()
                if remaining and remaining[0] not in ':,}]"':
                    result.append('\\"')
                    continue
                in_string = False
                result.append(char)
                # If we're at depth 0 and closed a top-level string, we're done
                if depth == 0 and not started_with_container:
                    return "".join(result)
            else:
                in_string = True
                result.append(char)
        elif in_string and char == "\n":
            result.append("\\n")
        else:
            result.append(char)

        if not in_string:
            if char in "[{":
                depth += 1
            elif char in "]}":
                depth -= 1
                if depth == 0:
                    return "".join(result)
            # For primitives at top level (depth 0), stop at whitespace if we've consumed content
            elif depth == 0 and not started_with_container and result and char in " \t\n\r":
                # Check if this is trailing whitespace after a complete primitive
                current = "".join(result).strip()
                if current:
                    try:
                        json.loads(current)
                        return current
                    except (json.JSONDecodeError, ValueError):
                        pass

    return "".join(result)


def forgiving_json_loads(text: str) -> Any:
    """
    Parse JSON from text, applying heuristics to fix common LLM mistakes.

    Repairs applied:
    - Strip leading/trailing non-JSON text
    - Escape unescaped quotes and newlines inside strings
    - Fix invalid escape sequences
    """
    if not text or not text.strip():
        raise ValueError("Empty or whitespace-only input")

    text = _repair_json(text)

    # Fix invalid escape sequences by escaping the backslash (e.g. \\x -> \\\\x).
    invalid_escape_pattern = r'\\(?![\\"/bfnrt]|u[0-9a-fA-F]{4})'
    text = re.sub(invalid_escape_pattern, lambda m: "\\\\" + m.group(0)[1:], text)

    return json.loads(text)
