import pytest

from docent.judges.util.voting import find_modal_result, get_agreement_keys


def test_find_modal_result_prefers_result_matching_most_modes():
    indep_results = [
        {"label": "match", "passed": True, "score": 1},
        {"label": "no match", "passed": False, "score": 2},
        {"label": "match", "passed": True, "score": 2},
        {"label": "match", "passed": False, "score": 1},
        {"label": "no match", "passed": True, "score": 1},
    ]

    max_idx, modes = find_modal_result(
        indep_results,
        ["label", "passed", "score"],
    )

    assert max_idx == 0
    assert modes == {
        "label": ("match", 3),
        "passed": (True, 3),
        "score": (1, 3),
    }


def test_find_modal_result_breaks_ties_by_lowest_index():
    indep_results = [
        {"label": "match", "passed": True},
        {"label": "match", "passed": True},
        {"label": "no match", "passed": False},
    ]

    max_idx, modes = find_modal_result(indep_results, ["label", "passed"])

    assert max_idx == 0
    assert modes == {
        "label": ("match", 2),
        "passed": (True, 2),
    }


def test_find_modal_result_raises_for_empty_results():
    with pytest.raises(ValueError, match="No results to score"):
        find_modal_result([], ["label"])


def test_find_modal_result_handles_empty_agreement_keys():
    indep_results = [
        {"label": "match"},
        {"label": "no match"},
    ]

    max_idx, modes = find_modal_result(indep_results, [])

    assert max_idx == 0
    assert modes == {}


def test_find_modal_result_skips_missing_field_when_scoring():
    indep_results = [
        {"label": "match", "passed": True},
        {"label": "match"},
        {"label": "no match"},
    ]

    max_idx, modes = find_modal_result(indep_results, ["label", "passed"])

    assert max_idx == 0
    assert modes == {
        "label": ("match", 2),
        "passed": (True, 1),
    }


def test_find_modal_result_records_none_when_no_values_present():
    indep_results = [
        {"label": "match"},
        {"label": "match"},
        {"label": "no match"},
    ]

    max_idx, modes = find_modal_result(indep_results, ["label", "score"])

    assert max_idx == 0
    assert modes == {
        "label": ("match", 2),
        "score": None,
    }


def test_get_agreement_keys_includes_expected_types():
    schema = {
        "type": "object",
        "properties": {
            "label": {"type": "string", "enum": ["match", "no match"]},
            "explanation": {"type": "string", "citations": True},
            "score": {"type": "integer", "enum": [0, 1, 2]},
            "confidence": {"type": "number"},
            "flag": {"type": "boolean"},
        },
    }

    assert get_agreement_keys(schema) == ["label", "score", "flag"]


def test_get_agreement_keys_skips_unsupported_fields():
    schema = {
        "type": "object",
        "properties": {
            "comment": {"type": "string"},
            "confidence": {"type": "number"},
            "details": {
                "type": "object",
                "properties": {
                    "nested_flag": {"type": "boolean"},
                },
            },
        },
    }

    assert get_agreement_keys(schema) == []


def test_get_agreement_keys_returns_empty_for_non_object():
    schema = {"type": "array", "items": {"type": "string"}}

    assert get_agreement_keys(schema) == []
