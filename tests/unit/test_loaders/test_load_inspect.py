"""Unit tests for score normalization when loading inspect logs."""

import io
import json
from typing import Any

import pytest

from docent.loaders.load_inspect import runs_from_file


def _load_scores(value: Any) -> Any:
    log: dict[str, Any] = {
        "samples": [{"id": 1, "epoch": 1, "messages": [], "scores": {"s": {"value": value}}}]
    }
    _, runs = runs_from_file(io.BytesIO(json.dumps(log).encode()), format="json")
    return next(runs).metadata["scores"]["s"]


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        ("C", 1.0),
        ("I", 0),
        ("P", 0.5),
        ("yes", 1.0),
        ("0.75", 0.75),
        (3, 3.0),
        # Signed and exponent strings are numbers, as in inspect_ai's value_to_float
        ("-1", -1.0),
        ("-0.5", -0.5),
        ("1e-3", 0.001),
        # Strings that only look numeric once the dots are removed are kept as strings
        ("1.2.3", "1.2.3"),
        ("192.168.0.1", "192.168.0.1"),
        ("\u00b2", "\u00b2"),
        ("nan", "nan"),
        ("Correct", "correct"),
    ],
)
def test_normalize_leaf_values(value: Any, expected: Any):
    assert _load_scores(value) == expected


@pytest.mark.unit
def test_normalize_dict_value_does_not_raise():
    value = {"margin": "-0.5", "version": "1.2.3", "includes": "C"}
    assert _load_scores(value) == {"margin": -0.5, "version": "1.2.3", "includes": 1.0}
