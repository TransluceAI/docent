"""Unit tests for citation parsing functions."""

from typing import Callable

import pytest

from docent.data_models.citation import (
    Citation,
    parse_citations_multi_run,
    parse_citations_single_run,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "parser_func,text,expected_citations,test_description",
    [
        # Single-run citation tests
        (parse_citations_single_run, "Basic [T1B2] citation.", [(1, 2)], "single_basic"),
        (
            parse_citations_single_run,
            "Multiple [T1B2, T3B4] citations.",
            [(1, 2), (3, 4)],
            "single_multiple",
        ),
        (
            parse_citations_single_run,
            "Range [T1B2-T3B4] citation.",
            [(1, 2), (3, 4)],
            "single_range",
        ),
        (
            parse_citations_single_run,
            "Complex [T1B2, T3B4-T5B6] citations.",
            [(1, 2), (3, 4), (5, 6)],
            "single_complex",
        ),
        (
            parse_citations_single_run,
            "Spaced [ T1B2 , T3B4 ] citations.",
            [(1, 2), (3, 4)],
            "single_whitespace",
        ),
        # Multi-run citation tests
        (parse_citations_multi_run, "Basic [R1T2B3] citation.", [(1, 2, 3)], "multi_basic"),
        (
            parse_citations_multi_run,
            "Multiple [R1T2B3, R4T5B6] citations.",
            [(1, 2, 3), (4, 5, 6)],
            "multi_multiple",
        ),
        (
            parse_citations_multi_run,
            "Range [R1T2B3-R4T5B6] citation.",
            [(1, 2, 3), (4, 5, 6)],
            "multi_range",
        ),
        (
            parse_citations_multi_run,
            "Parentheses ([R1T2B3]) citation.",
            [(1, 2, 3)],
            "multi_parentheses",
        ),
        (
            parse_citations_multi_run,
            "Spaced [ R1T2B3 , R4T5B6 ] citations.",
            [(1, 2, 3), (4, 5, 6)],
            "multi_whitespace",
        ),
    ],
)
def test_valid_citations(
    parser_func: Callable[[str], list[Citation]],
    text: str,
    expected_citations: list[tuple[int, ...]],
    test_description: str,
):
    """Test parsing of valid citation patterns."""
    result = parser_func(text)
    assert len(result) == len(expected_citations), f"Failed for {test_description}"

    # Convert results to tuples for comparison
    if parser_func == parse_citations_single_run:
        actual_citations = [(c["transcript_idx"], c["block_idx"]) for c in result]
    else:
        actual_citations = [
            (c["agent_run_idx"], c["transcript_idx"], c["block_idx"]) for c in result
        ]

    # Verify all expected citations are present
    for expected in expected_citations:
        assert expected in actual_citations, f"Missing citation {expected} in {test_description}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "parser_func,text,test_description",
    [
        (parse_citations_single_run, "No citations here.", "single_none"),
        (parse_citations_single_run, "", "single_empty"),
        (parse_citations_single_run, "Invalid [brackets] content.", "single_invalid"),
        (parse_citations_multi_run, "No citations here.", "multi_none"),
        (parse_citations_multi_run, "", "multi_empty"),
        (parse_citations_multi_run, "Invalid [brackets] content.", "multi_invalid"),
    ],
)
def test_no_citations_found(
    parser_func: Callable[[str], list[Citation]],
    text: str,
    test_description: str,
):
    """Test cases where no valid citations should be found."""
    result = parser_func(text)
    assert len(result) == 0, f"Expected no citations for {test_description}"
