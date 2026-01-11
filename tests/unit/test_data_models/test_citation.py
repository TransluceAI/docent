"""Unit tests for citation parsing functions."""

import pytest

from docent.data_models.citation import (
    parse_citations,
    parse_single_citation,
    scan_brackets,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected_aliases,test_description",
    [
        ("Basic [T1B2] citation.", ["T1B2"], "single_basic"),
        ("Multiple [T1B2] and [T3B4] citations.", ["T1B2", "T3B4"], "single_multiple"),
        ("Spaced [ T1B2 ] citations.", ["T1B2"], "single_whitespace"),
    ],
)
def test_valid_citations(
    text: str,
    expected_aliases: list[str],
    test_description: str,
):
    """Test parsing of valid citation patterns."""
    _cleaned, result = parse_citations(text)
    assert len(result) == len(expected_aliases), f"Failed for {test_description}"

    # Convert results to aliases for comparison
    actual_aliases = [c.item_alias for c in result]

    # Verify all expected citations are present
    for expected in expected_aliases:
        assert expected in actual_aliases, f"Missing citation {expected} in {test_description}"


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,test_description",
    [
        ("No citations here.", "none"),
        ("", "empty"),
    ],
)
def test_no_citations_found(
    text: str,
    test_description: str,
):
    """Test cases where no valid citations should be found."""
    _cleaned, result = parse_citations(text)
    assert len(result) == 0, f"Expected no citations for {test_description}"


@pytest.mark.unit
def test_citation_indices():
    """Test that citation indices are calculated correctly."""
    text = "Before [T1B2] middle [T3B4] after"
    cleaned, citations = parse_citations(text)

    # Note: parse_citations currently doesn't clean text (returns as-is)
    assert cleaned == text

    # Verify citation count
    assert len(citations) == 2

    # Verify first citation
    assert citations[0].item_alias == "T1B2"
    assert citations[0].start_idx == 7  # "Before ["
    assert citations[0].end_idx == 13  # "Before [T1B2]"

    # Verify second citation
    assert citations[1].item_alias == "T3B4"
    assert citations[1].start_idx == 21  # "Before [T1B2] middle ["
    assert citations[1].end_idx == 27  # "Before [T1B2] middle [T3B4]"


@pytest.mark.unit
def test_range_markers_in_regular_text():
    """Test that range markers in regular text are preserved, not stripped."""
    text = "Text with <RANGE>markers</RANGE> and [T1B2] citation."
    cleaned, citations = parse_citations(text)

    # Range markers in regular text should be preserved
    assert "<RANGE>markers</RANGE>" in cleaned

    # Citation should still be parsed correctly
    assert len(citations) == 1
    assert citations[0].item_alias == "T1B2"


@pytest.mark.unit
def test_range_markers_in_citations():
    """Test that range markers inside citations are processed correctly."""
    text = "Text with [T1B2:<RANGE>pattern</RANGE>] citation."
    _cleaned, citations = parse_citations(text)

    # Citation should be parsed with text range
    assert len(citations) == 1
    assert citations[0].item_alias == "T1B2"
    assert citations[0].text_range is not None
    assert citations[0].text_range.start_pattern == "pattern"


@pytest.mark.unit
@pytest.mark.parametrize(
    "text,expected_data,test_description",
    [
        # Agent run metadata
        (
            "The task was [M.task_description] and it succeeded.",
            [("M.task_description", None)],
            "agent_run_metadata",
        ),
        # Transcript metadata
        (
            "Started at [T0M.start_time] according to the logs.",
            [("T0M.start_time", None)],
            "transcript_metadata",
        ),
        # Message metadata
        (
            "The message status was [T0B1M.status] at that point.",
            [("T0B1M.status", None)],
            "message_metadata",
        ),
        # Message metadata with text range
        (
            "The response contained [T0B1M.result:<RANGE>success</RANGE>] indicating completion.",
            [("T0B1M.result", "success")],
            "message_metadata_with_range",
        ),
        # Mixed citations
        (
            "Agent [M.name] processed [T0B1] with status [T1B2M.result].",
            [("M.name", None), ("T0B1", None), ("T1B2M.result", None)],
            "mixed_citations",
        ),
    ],
)
def test_metadata_citations(
    text: str,
    expected_data: list[tuple[str, str | None]],
    test_description: str,
):
    """Test parsing of metadata citation patterns."""
    _cleaned, result = parse_citations(text)
    assert len(result) == len(expected_data), (
        f"Failed for {test_description}: expected {len(expected_data)} citations, got {len(result)}"
    )

    # Convert results to tuples for comparison (item_alias, text_range_pattern)
    actual_data = [
        (c.item_alias, c.text_range.start_pattern if c.text_range else None) for c in result
    ]

    # Verify all expected citations are present
    for expected in expected_data:
        assert expected in actual_data, (
            f"Missing citation {expected} in {test_description}. Got: {actual_data}"
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "citation_text,expected_alias,expected_pattern",
    [
        # Agent run metadata
        ("M.task_description", "M.task_description", None),
        # Transcript metadata
        ("T0M.start_time", "T0M.start_time", None),
        # Message metadata
        ("T0B1M.status", "T0B1M.status", None),
        # Message metadata with range
        ("T0B1M.result:<RANGE>success</RANGE>", "T0B1M.result", "success"),
        # Regular transcript block
        ("T0B1", "T0B1", None),
        # Regular transcript block with range
        ("T0B1:<RANGE>pattern</RANGE>", "T0B1", "pattern"),
    ],
)
def test_parse_single_citation(
    citation_text: str, expected_alias: str, expected_pattern: str | None
):
    """Test the parse_single_citation function."""
    result = parse_single_citation(citation_text)
    assert result is not None, f"Failed to parse '{citation_text}'"
    alias, text_range = result
    assert alias == expected_alias, (
        f"Failed for '{citation_text}': expected alias {expected_alias}, got {alias}"
    )
    if expected_pattern:
        assert text_range is not None
        assert text_range.start_pattern == expected_pattern
    else:
        assert text_range is None or text_range.start_pattern is None


@pytest.mark.unit
def test_parse_single_citation_invalid():
    """Test that invalid citations return None."""
    result = parse_single_citation("")
    assert result is None


@pytest.mark.unit
def test_scan_brackets_nested():
    """Test that scan_brackets handles nested brackets correctly."""
    text = "Text [outer [inner] content] more"
    results = scan_brackets(text)
    assert len(results) == 1
    assert results[0][2] == "outer [inner] content"


@pytest.mark.unit
def test_scan_brackets_with_range_markers():
    """Test that scan_brackets respects RANGE markers and doesn't count brackets inside."""
    text = "Text [T0B1:<RANGE>content with [brackets]</RANGE>] more"
    results = scan_brackets(text)
    assert len(results) == 1
    assert results[0][2] == "T0B1:<RANGE>content with [brackets]</RANGE>"
