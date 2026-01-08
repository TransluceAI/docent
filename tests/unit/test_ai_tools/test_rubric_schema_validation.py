import jsonschema
import pytest

from docent.judges.types import Rubric
from docent.judges.util.meta_schema import validate_judge_result_schema


def _valid_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "score": {"type": "number"},
        },
        "required": ["label"],
        "additionalProperties": False,
    }


def test_validate_judge_result_schema_accepts_valid_schema():
    validate_judge_result_schema(_valid_schema())


def test_validate_judge_result_schema_missing_properties_raises_validation_error():
    with pytest.raises(jsonschema.ValidationError, match="'properties' is a required property"):
        validate_judge_result_schema({"type": "object"})


def test_validate_judge_result_schema_unknown_type_raises_schema_error():
    schema = {
        "type": "object",
        "properties": {"label": {"type": "invalid"}},
    }

    with pytest.raises(
        jsonschema.SchemaError, match="'invalid' is not valid under any of the given schemas"
    ):
        validate_judge_result_schema(schema)


def test_rubric_accepts_valid_output_schema():
    rubric = Rubric(rubric_text="Example rubric", output_schema=_valid_schema())
    assert rubric.output_schema["required"] == ["label"]


def test_rubric_invalid_schema_missing_properties_propagates_validation_error():
    with pytest.raises(jsonschema.ValidationError, match="'properties' is a required property"):
        Rubric(rubric_text="Example rubric", output_schema={"type": "object"})


def test_rubric_invalid_schema_unknown_type_propagates_schema_error():
    schema = {
        "type": "object",
        "properties": {"label": {"type": "madeup"}},
    }

    with pytest.raises(
        jsonschema.SchemaError, match="'madeup' is not valid under any of the given schemas"
    ):
        Rubric(rubric_text="Example rubric", output_schema=schema)


# --- Tests for array and nested schema support ---


def test_validate_judge_result_schema_accepts_array_of_strings():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "label": {"type": "string", "enum": ["safe", "unsafe"]},
            "tags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["label", "tags"],
    }
    validate_judge_result_schema(schema)


def test_validate_judge_result_schema_accepts_array_of_integers_with_constraints():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "scores": {
                "type": "array",
                "items": {"type": "integer", "minimum": 0, "maximum": 10},
            }
        },
        "required": ["scores"],
    }
    validate_judge_result_schema(schema)


def test_validate_judge_result_schema_accepts_array_of_objects():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "category": {"type": "string", "enum": ["bug", "security", "performance"]},
                        "severity": {"type": "integer", "minimum": 1, "maximum": 5},
                        "description": {"type": "string", "citations": True},
                    },
                    "required": ["category", "severity"],
                },
            }
        },
        "required": ["findings"],
    }
    validate_judge_result_schema(schema)


def test_validate_judge_result_schema_accepts_deeply_nested_structure():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "analysis": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "title": {"type": "string"},
                                "issues": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "additionalProperties": False,
                                        "properties": {
                                            "line": {"type": "integer", "minimum": 1},
                                            "message": {"type": "string", "citations": True},
                                        },
                                        "required": ["line", "message"],
                                    },
                                },
                            },
                            "required": ["title", "issues"],
                        },
                    }
                },
                "required": ["sections"],
            }
        },
        "required": ["analysis"],
    }
    validate_judge_result_schema(schema)


def test_validate_judge_result_schema_array_items_missing_type_raises_error():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"tags": {"type": "array", "items": {"description": "A tag"}}},
        "required": ["tags"],
    }
    with pytest.raises(jsonschema.ValidationError, match="'type' is a required property"):
        validate_judge_result_schema(schema)


def test_validate_judge_result_schema_unsupported_type_null_raises_error():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"data": {"type": "array", "items": {"type": "null"}}},
        "required": ["data"],
    }
    with pytest.raises(jsonschema.ValidationError, match="'null' is not one of"):
        validate_judge_result_schema(schema)


def test_validate_judge_result_schema_extra_property_raises_error():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"label": {"type": "string", "enum": ["a", "b"], "default": "a"}},
        "required": ["label"],
    }
    with pytest.raises(jsonschema.ValidationError, match="Additional properties are not allowed"):
        validate_judge_result_schema(schema)


def test_validate_judge_result_schema_array_missing_items_raises_error():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"tags": {"type": "array"}},
        "required": ["tags"],
    }
    with pytest.raises(jsonschema.ValidationError, match="'items' is a required property"):
        validate_judge_result_schema(schema)


def test_validate_judge_result_schema_nested_object_missing_properties_raises_error():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {"metadata": {"type": "object"}},
        "required": ["metadata"],
    }
    with pytest.raises(jsonschema.ValidationError, match="'properties' is a required property"):
        validate_judge_result_schema(schema)
