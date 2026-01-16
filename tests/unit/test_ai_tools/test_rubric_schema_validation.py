import jsonschema
import pytest

from docent.judges.types import OutputParsingMode, PromptTemplateMessage, Rubric
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


# --- Regression test for model_copy validation bypass ---


def test_rubric_model_copy_bypasses_validation():
    """Documents that model_copy does NOT run validators.

    This is NOT a bug in Pydantic - it's expected behavior. The bug was in
    rewrite_rubric() using model_copy when it should use model_validate.
    This test documents the dangerous behavior to prevent future misuse.
    """
    valid_rubric = Rubric(rubric_text="Example rubric", output_schema=_valid_schema())

    invalid_schema = {"type": "object"}  # Missing required 'properties'

    # model_copy does NOT raise - this is why we must use model_validate
    invalid_rubric = valid_rubric.model_copy(update={"output_schema": invalid_schema})

    # The rubric now contains an invalid schema!
    assert invalid_rubric.output_schema == invalid_schema


def test_rubric_model_validate_with_invalid_schema_raises_validation_error():
    """Regression test: updating Rubric's output_schema must trigger validation.

    This test ensures that updating a Rubric's output_schema via model_validate
    properly validates the new schema. Previously, model_copy bypassed validators,
    allowing invalid schemas to be persisted to the database.

    See: docent_core/docent/ai_tools/rubric/rewrite.py - rewrite_rubric()
    """
    valid_rubric = Rubric(rubric_text="Example rubric", output_schema=_valid_schema())

    invalid_schema = {"type": "object"}  # Missing required 'properties'

    # Using model_validate should trigger the output_schema validator
    with pytest.raises(jsonschema.ValidationError, match="'properties' is a required property"):
        Rubric.model_validate(valid_rubric.model_dump() | {"output_schema": invalid_schema})


# --- Tests for XML key validation with prompt_templates ---


def test_rubric_xml_key_validation_fails_when_prompt_templates_missing_xml_tag():
    """Validates that XML_KEY mode checks prompt_templates when set.

    Previously, the validator incorrectly checked the default template as well as prompt_templates,
    allowing validation to pass when prompt_templates lacked the XML tag but the default
    template contained it. This caused silent runtime failures.
    """
    # Include required template variables to pass the template validation
    template_content = (
        "Rubric: {rubric}\nAgent run: {agent_run}\nSchema: {output_schema}\n"
        "Output JSON without XML tags."
    )
    with pytest.raises(ValueError, match="must contain the XML tag '<response>'"):
        Rubric(
            rubric_text="Example rubric",
            output_schema=_valid_schema(),
            prompt_templates=[
                PromptTemplateMessage(role="user", content=template_content),
            ],
            output_parsing_mode=OutputParsingMode.XML_KEY,
        )


def test_rubric_xml_key_validation_passes_when_prompt_templates_contains_xml_tag():
    """Verifies validation passes when prompt_templates contains the required XML tag."""
    template_content = (
        "Rubric: {rubric}\nAgent run: {agent_run}\nSchema: {output_schema}\n"
        "Output your response in <response>...</response> tags."
    )
    rubric = Rubric(
        rubric_text="Example rubric",
        output_schema=_valid_schema(),
        prompt_templates=[
            PromptTemplateMessage(role="user", content=template_content),
        ],
        output_parsing_mode=OutputParsingMode.XML_KEY,
    )
    assert rubric.output_parsing_mode == OutputParsingMode.XML_KEY
