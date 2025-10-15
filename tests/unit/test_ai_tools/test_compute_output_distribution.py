from typing import Any

from docent.judges.util.voting import compute_output_distribution


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

    distributions = compute_output_distribution(indep_results, output_schema, agreement_keys)

    expected: dict[str, dict[str | bool | int | float, float]] = {
        "grade": {"pass": 2 / 3, "fail": 1 / 3, "partial": 0.0}
    }
    assert distributions.keys() == expected.keys()
    assert distributions["grade"].keys() == expected["grade"].keys()
    for value, prob in distributions["grade"].items():
        assert prob == expected["grade"][value]


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

    distributions = compute_output_distribution(indep_results, output_schema, agreement_keys)

    expected: dict[str, dict[str | bool | int | float, float]] = {
        "approved": {True: 2 / 3, False: 1 / 3}
    }
    assert distributions.keys() == expected.keys()
    assert distributions["approved"].keys() == expected["approved"].keys()
    for value, prob in distributions["approved"].items():
        assert prob == expected["approved"][value]


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

    distributions = compute_output_distribution(indep_results, output_schema, agreement_keys)

    assert distributions == {"approved": {True: 0.0, False: 0.0}}
