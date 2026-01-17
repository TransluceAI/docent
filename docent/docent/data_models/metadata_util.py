import json
from typing import Any, cast

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


def deep_merge_metadata(destination: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively merge metadata dictionaries in-place.

    Nested dictionaries are merged to preserve existing keys while allowing
    later values to override earlier ones.
    """
    for key, value in source.items():
        dest_value = destination.get(key)
        if isinstance(dest_value, dict) and isinstance(value, dict):
            deep_merge_metadata(cast(dict[str, Any], dest_value), cast(dict[str, Any], value))
        else:
            destination[key] = value
    return destination
