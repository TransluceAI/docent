import json
from pathlib import Path
from typing import Any

import jsonschema


def _load_meta_schema_json() -> str:
    """Load the rubric meta-schema JSON string from the adjacent file."""
    meta_schema_path = Path(__file__).with_suffix(".json")
    with meta_schema_path.open("r", encoding="utf-8") as f:
        return f.read()


# Load once at module import time
_META_SCHEMA_JSON = _load_meta_schema_json()
_META_SCHEMA = json.loads(_META_SCHEMA_JSON)
_META_VALIDATOR = jsonschema.Draft202012Validator(_META_SCHEMA)


def get_meta_schema_json() -> str:
    """Return the raw meta-schema JSON string for inclusion in prompts."""
    return _META_SCHEMA_JSON


def validate_judge_result_schema(schema: dict[str, Any]):
    """Validate a proposed schema against the rubric meta-schema.

    Raises:
        jsonschema.ValidationError: If the schema is invalid
        jsonschema.SchemaError: If the schema is not a valid 2020-12 schema
    """
    # First check that this is a valid 2020-12 schema
    jsonschema.Draft202012Validator.check_schema(schema)

    # Then check that it conforms to our subset of the 2020-12 schema
    _META_VALIDATOR.validate(schema)  # type: ignore
