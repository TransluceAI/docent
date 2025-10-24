from typing import Any

from docent.judges.util.voting import compute_output_distributions


def test_compute_output_distribution_with_enum_values():
    indep_results: list[dict[str, Any]] = [
        {"grade": "pass"},
        {"grade": "fail"},
        {"grade": "pass"},
    ]
    output_schema = {
        "properties": {
            "grade": {
                "type": "string",
                "enum": ["pass", "fail", "partial"],
            }
        }
    }
    agreement_keys = ["grade"]

    distributions = compute_output_distributions(indep_results, output_schema, agreement_keys)

    expected: dict[str, dict[str | bool | int | float, float]] = {
        "grade": {"pass": 2 / 3, "fail": 1 / 3, "partial": 0.0}
    }
    assert distributions.keys() == expected.keys()
    assert distributions["grade"].keys() == expected["grade"].keys()
    for value, stats in distributions["grade"].items():
        assert stats["mean"] == expected["grade"][value]


def test_compute_output_distribution_with_boolean_values_and_missing_keys():
    indep_results: list[dict[str, Any]] = [
        {"approved": True},
        {"approved": False},
        {"approved": True},
        {"other": "value"},
    ]
    output_schema = {
        "properties": {
            "approved": {
                "type": "boolean",
            }
        }
    }
    agreement_keys = ["approved"]

    distributions = compute_output_distributions(indep_results, output_schema, agreement_keys)

    expected: dict[str, dict[str | bool | int | float, float]] = {
        "approved": {True: 2 / 3, False: 1 / 3}
    }
    assert distributions.keys() == expected.keys()
    assert distributions["approved"].keys() == expected["approved"].keys()
    for value, stats in distributions["approved"].items():
        assert stats["mean"] == expected["approved"][value]


def test_compute_output_distribution_when_no_values_present():
    indep_results: list[dict[str, Any]] = [
        {"other": "value"},
        {},
    ]
    output_schema = {
        "properties": {
            "approved": {
                "type": "boolean",
            }
        }
    }
    agreement_keys = ["approved"]

    distributions = compute_output_distributions(indep_results, output_schema, agreement_keys)

    assert distributions.keys() == {"approved"}
    assert distributions["approved"].keys() == {True, False}
    for value in distributions["approved"]:
        assert distributions["approved"][value]["mean"] == 0.0


def test_compute_output_distribution_multiple_keys_with_optional_values():
    indep_results: list[dict[str, Any]] = [
        {"label": "match", "flag": True, "score": 1},
        {"label": "match", "score": 0},
        {"label": "no match", "flag": False},
        {"label": "match"},
        {"flag": True},
    ]
    output_schema = {
        "properties": {
            "label": {
                "type": "string",
                "enum": ["match", "no match"],
            },
            "flag": {
                "type": "boolean",
            },
            "score": {
                "type": "integer",
                "enum": [0, 1, 2],
            },
            "reviewed": {
                "type": "boolean",
            },
        }
    }
    agreement_keys = ["label", "flag", "score", "reviewed"]

    distributions = compute_output_distributions(indep_results, output_schema, agreement_keys)

    expected: dict[str, dict[str | bool | int | float, float]] = {
        "label": {"match": 3 / 4, "no match": 1 / 4},
        "flag": {True: 2 / 3, False: 1 / 3},
        "score": {0: 1 / 2, 1: 1 / 2, 2: 0.0},
        "reviewed": {True: 0.0, False: 0.0},
    }
    assert distributions.keys() == expected.keys()
    for key in expected:
        assert distributions[key].keys() == expected[key].keys()
        for value, prob in expected[key].items():
            assert distributions[key][value]["mean"] == prob
