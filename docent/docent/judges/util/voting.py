from collections import Counter
from typing import Any, TypedDict, cast

import numpy as np


class EstimateWithCI(TypedDict):
    mean: float
    var: float
    n: int
    ci_95: float


JudgeOutputDistribution = dict[str | bool | int | float, EstimateWithCI]


def get_agreement_keys(schema: dict[str, Any]) -> list[str]:
    """Get list of top-level keys in schema that we want to measure agreement on.

    This includes enum and bool fields.

    Args:
        schema: JSON schema dict

    Returns:
        List of field names (keys) that should be used for measuring agreement
    """
    agreement_keys: list[str] = []

    properties = schema.get("properties", {})
    assert isinstance(properties, dict)
    properties = cast(dict[str, Any], properties)

    for key, field_schema in properties.items():
        assert isinstance(field_schema, dict)
        field_schema = cast(dict[str, Any], field_schema)

        field_type = field_schema.get("type")
        assert isinstance(field_type, str)

        # Include boolean fields
        if field_type == "boolean":
            agreement_keys.append(key)
        # Include enum fields (strings and numbers must be in this category)
        elif "enum" in field_schema:
            agreement_keys.append(key)

    return agreement_keys


def find_modal_result(indep_results: list[dict[str, Any]], agreement_keys: list[str]):
    """Find the result that best matches modal values across agreement keys.

    Args:
        indep_results: List of independent results to analyze
        agreement_keys: Keys to measure agreement on

    Returns:
        Tuple of (max_idx, agt_key_modes_and_counts) where:
        - max_idx is the index of the result that best matches modal values
        - agt_key_modes_and_counts maps each key to (modal_value, count) or None if no values exist for that key

    Raises:
        ValueError: If no results are provided
    """
    if not indep_results:
        raise ValueError("No results to score")

    # For each agreement key, compute the mode and count (or None, if no values exist for that key)
    agt_key_modes_and_counts: dict[str, tuple[str | bool | int, int] | None] = {}
    for key in agreement_keys:
        key_modes = Counter(v for r in indep_results if (v := r.get(key)) is not None)
        if most_common_one := key_modes.most_common(1):
            agt_key_modes_and_counts[key] = most_common_one[0]
        else:
            agt_key_modes_and_counts[key] = None

    # Score each rollout based on how many agreement keys they match
    # If there is no mode for a key, or if a certain result doesn't have that key, it doesn't count.
    # TODO(mengk): This may bias towards results that have more keys.
    indep_result_scores: list[int] = []
    for r in indep_results:
        score = 0
        for key in agreement_keys:
            mode_and_count = agt_key_modes_and_counts[key]
            if mode_and_count and r.get(key) == mode_and_count[0]:
                score += 1
        indep_result_scores.append(score)

    # Argmax
    max_idx = indep_result_scores.index(max(indep_result_scores))

    return max_idx, agt_key_modes_and_counts


def compute_output_distributions(
    indep_results: list[dict[str, Any]], output_schema: dict[str, Any], agreement_keys: list[str]
):
    def _get_possible_values(key: str) -> list[str | bool | int | float]:
        if "enum" in output_schema.get("properties", {}).get(key, {}):
            return output_schema.get("properties", {}).get(key, {}).get("enum", [])
        elif output_schema.get("properties", {}).get(key, {}).get("type") == "boolean":
            return [True, False]
        else:
            return []

    raw_counts: dict[str, dict[str | bool | int | float, int]] = {
        key: {value: 0 for value in _get_possible_values(key)} for key in agreement_keys
    }
    # Collect counts for each possible value
    for result in indep_results:
        for key in agreement_keys:
            if (value := result.get(key)) is not None:  # Could be none if the key is optional
                assert (
                    value in raw_counts[key]
                ), "this should never happen; the value must be in possible values, since judge results have been validated against the schema"
                raw_counts[key][value] += 1

    distributions: dict[str, JudgeOutputDistribution] = {}
    for agt_key in agreement_keys:
        distributions[agt_key] = {}

        # First normalize the counts to get probabilities
        counts = raw_counts[agt_key]
        total = sum(counts.values())
        probs = {value: (count / total) if total > 0 else 0.0 for value, count in counts.items()}

        for output_key, value in probs.items():
            mean, estimate_var = value, (value * (1 - value))
            # TODO(mengk): change to the wilson score interval
            ci_95 = float(1.96 * np.sqrt(estimate_var / total)) if total > 0 else 0.0
            distributions[agt_key][output_key] = {
                "mean": mean,
                "var": estimate_var,
                "n": total,
                "ci_95": ci_95,
            }

    return distributions
