"""Unit tests for citation parsing functions."""

from typing import Callable

import pytest

from docent.data_models.citation import (
    Citation,
    ParsedCitation,
    parse_citations,
    parse_single_citation,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "parser_func,text,expected_citations,test_description",
    [
        # Single-run citation tests
        (parse_citations, "Basic [T1B2] citation.", [(1, 2)], "single_basic"),
        (
            parse_citations,
            "Multiple [T1B2] and [T3B4] citations.",
            [(1, 2), (3, 4)],
            "single_multiple",
        ),
        (
            parse_citations,
            "Spaced [ T1B2 ] citations.",
            [(1, 2)],
            "single_whitespace",
        ),
    ],
)
def test_valid_citations(
    parser_func: Callable[[str], tuple[str, list[Citation]]],
    text: str,
    expected_citations: list[tuple[int, ...]],
    test_description: str,
):
    """Test parsing of valid citation patterns."""
    _cleaned, result = parser_func(text)
    assert len(result) == len(expected_citations), f"Failed for {test_description}"

    # Convert results to tuples for comparison
    actual_citations = [(c.transcript_idx, c.block_idx) for c in result]

    # Verify all expected citations are present
    for expected in expected_citations:
        assert expected in actual_citations, f"Missing citation {expected} in {test_description}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "parser_func,text,test_description",
    [
        (parse_citations, "No citations here.", "none"),
        (parse_citations, "", "empty"),
        (parse_citations, "Invalid [brackets] content.", "invalid"),
    ],
)
def test_no_citations_found(
    parser_func: Callable[[str], tuple[str, list[Citation]]],
    text: str,
    test_description: str,
):
    """Test cases where no valid citations should be found."""
    _cleaned, result = parser_func(text)
    assert len(result) == 0, f"Expected no citations for {test_description}"


@pytest.mark.unit
def test_citation_indices():
    """Test that citation indices are calculated correctly in the cleaned text."""
    text = "Before [T1B2] middle [T3B4] after"
    cleaned, citations = parse_citations(text)

    # Verify cleaned text
    assert cleaned == "Before T1B2 middle T3B4 after"

    # Verify citation count
    assert len(citations) == 2

    # Verify first citation
    assert citations[0].transcript_idx == 1
    assert citations[0].block_idx == 2
    assert citations[0].start_idx == 7  # "Before " = 7 chars
    assert citations[0].end_idx == 11  # "Before T1B2" = 11 chars
    assert cleaned[citations[0].start_idx : citations[0].end_idx] == "T1B2"

    # Verify second citation
    assert citations[1].transcript_idx == 3
    assert citations[1].block_idx == 4
    assert citations[1].start_idx == 19  # "Before T1B2 middle " = 19 chars
    assert citations[1].end_idx == 23  # "Before T1B2 middle T3B4" = 23 chars
    assert cleaned[citations[1].start_idx : citations[1].end_idx] == "T3B4"


@pytest.mark.unit
def test_range_markers_in_regular_text():
    """Test that range markers in regular text are preserved, not stripped."""
    text = "Text with <RANGE>markers</RANGE> and [T1B2] citation."
    cleaned, citations = parse_citations(text)

    # Range markers in regular text should be preserved
    assert "<RANGE>markers</RANGE>" in cleaned
    assert cleaned == "Text with <RANGE>markers</RANGE> and T1B2 citation."

    # Citation should still be parsed correctly
    assert len(citations) == 1
    assert citations[0].transcript_idx == 1
    assert citations[0].block_idx == 2


@pytest.mark.unit
def test_range_markers_in_citations():
    """Test that range markers inside citations are processed correctly."""
    text = "Text with [T1B2:<RANGE>pattern</RANGE>] citation."
    cleaned, citations = parse_citations(text)

    # Citation bracket and range markers should be removed from cleaned text
    assert cleaned == "Text with T1B2 citation."

    # Citation should be parsed with range patterns
    assert len(citations) == 1
    assert citations[0].transcript_idx == 1
    assert citations[0].block_idx == 2
    assert citations[0].start_pattern == "pattern"


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected_citations,test_description",
    [
        # Agent run metadata
        (
            "The task was [M.task_description] and it succeeded.",
            [(None, None, "task_description", None)],
            "agent_run_metadata",
        ),
        # Transcript metadata
        (
            "Started at [T0M.start_time] according to the logs.",
            [(0, None, "start_time", None)],
            "transcript_metadata",
        ),
        # Message metadata
        (
            "The message status was [T0B1M.status] at that point.",
            [(0, 1, "status", None)],
            "message_metadata",
        ),
        # Message metadata with text range
        (
            "The response contained [T0B1M.result:<RANGE>success</RANGE>] indicating completion.",
            [(0, 1, "result", "success")],
            "message_metadata_with_range",
        ),
        # Mixed citations
        (
            "Agent [M.name] processed [T0B1] with status [T1B2M.result].",
            [(None, None, "name", None), (0, 1, None, None), (1, 2, "result", None)],
            "mixed_citations",
        ),
    ],
)
def test_metadata_citations(
    text: str,
    expected_citations: list[tuple[int | None, int, str | None, str | None]],
    test_description: str,
):
    """Test parsing of metadata citation patterns."""
    _cleaned, result = parse_citations(text)
    assert len(result) == len(
        expected_citations
    ), f"Failed for {test_description}: expected {len(expected_citations)} citations, got {len(result)}"

    # Convert results to tuples for comparison (transcript_idx, block_idx, metadata_key, start_pattern)
    actual_citations = [
        (c.transcript_idx, c.block_idx, c.metadata_key, c.start_pattern) for c in result
    ]

    # Verify all expected citations are present
    for expected in expected_citations:
        assert (
            expected in actual_citations
        ), f"Missing citation {expected} in {test_description}. Got: {actual_citations}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "citation_text,expected",
    [
        # Agent run metadata
        ("M.task_description", ParsedCitation(None, None, "task_description")),
        # Transcript metadata
        ("T0M.start_time", ParsedCitation(0, None, "start_time")),
        # Message metadata
        ("T0B1M.status", ParsedCitation(0, 1, "status")),
        # Message metadata with range
        ("T0B1M.result:<RANGE>success</RANGE>", ParsedCitation(0, 1, "result", "success")),
        # Regular transcript block
        ("T0B1", ParsedCitation(0, 1)),
        # Regular transcript block with range
        ("T0B1:<RANGE>pattern</RANGE>", ParsedCitation(0, 1, start_pattern="pattern")),
        # Invalid citation
        ("invalid", None),
    ],
)
def test_parse_single_citation(citation_text: str, expected: ParsedCitation | None):
    """Test the parse_single_citation function with dataclass return type."""
    result = parse_single_citation(citation_text)
    assert result == expected, f"Failed for '{citation_text}': expected {expected}, got {result}"
