import json
from typing import Any

from pydantic_core import to_jsonable_python


def dump_metadata(metadata: dict[str, Any]) -> str | None:
    """
    Dump metadata to a JSON string.
    We used to use YAML to save tokens, but JSON makes it easier to find cited ranges on the frontend because the frontend uses JSON.
    """
    if not metadata:
        return None
    metadata_obj = to_jsonable_python(metadata)
    text = json.dumps(metadata_obj, indent=2)
    return text.strip()
