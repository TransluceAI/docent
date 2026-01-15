"""Unit tests for citation_transform module."""

import json

from docent_core.docent.utils.citation_transform import (
    build_escape_mapping,
    transform_output_for_chat,
)


class TestBuildEscapeMapping:
    """Tests for build_escape_mapping function."""

    def test_simple_text_no_escaping(self):
        """Plain text should have 1:1 mapping."""
        text = "hello"
        mapping = build_escape_mapping(text)
        assert mapping == [0, 1, 2, 3, 4, 5]

    def test_text_with_quotes(self):
        """Quotes get escaped to \\", adding 1 char each."""
        text = 'say "hi"'
        mapping = build_escape_mapping(text)
        # s=0, a=1, y=2, space=3, "=4 (becomes \"), h=6, i=7, "=8 (becomes \")
        assert mapping[0] == 0  # s
        assert mapping[4] == 4  # first " starts at 4
        assert mapping[5] == 6  # h is at 6 (after \")
        assert mapping[7] == 8  # second " starts at 8
        assert mapping[8] == 10  # end position

    def test_text_with_newline(self):
        """Newlines get escaped to \\n, adding 1 char each."""
        text = "line1\nline2"
        mapping = build_escape_mapping(text)
        # l=0, i=1, n=2, e=3, 1=4, \n=5 (becomes \\n), l=7, i=8, n=9, e=10, 2=11
        assert mapping[5] == 5  # newline starts at 5
        assert mapping[6] == 7  # 'l' of line2 is at 7
        assert mapping[11] == 12  # end position

    def test_text_with_backslash(self):
        """Backslashes get escaped to \\\\, adding 1 char each."""
        text = "path\\to"
        mapping = build_escape_mapping(text)
        # p=0, a=1, t=2, h=3, \=4 (becomes \\), t=6, o=7
        assert mapping[4] == 4  # backslash starts at 4
        assert mapping[5] == 6  # 't' is at 6
        assert mapping[7] == 8  # end position

    def test_empty_string(self):
        """Empty string should have single end position."""
        mapping = build_escape_mapping("")
        assert mapping == [0]


class TestTransformOutputForChat:
    """Tests for transform_output_for_chat function."""

    def test_default_schema_simple(self):
        """Default schema output with simple text and citations."""
        output = {
            "output": {
                "text": "The agent did X",
                "citations": [
                    {"start_idx": 14, "end_idx": 15, "transcript_id": "t1", "turn_number": 0}
                ],
            }
        }

        json_str, citations = transform_output_for_chat(output)

        # Verify JSON structure
        parsed = json.loads(json_str)
        assert parsed == {"output": "The agent did X"}

        # Verify citation was adjusted
        assert len(citations) == 1
        cite = citations[0]

        # Find where the text is in the JSON string
        assert json_str[cite["start_idx"] : cite["end_idx"]] == "X"

    def test_custom_schema_multiple_fields(self):
        """Custom schema with multiple fields, one having citations."""
        output = {
            "category": "helpful",
            "confidence": 0.9,
            "reasoning": {
                "text": "The agent helped by doing ABC",
                "citations": [
                    {"start_idx": 26, "end_idx": 29, "transcript_id": "t1", "turn_number": 5}
                ],
            },
        }

        json_str, citations = transform_output_for_chat(output)

        # Verify JSON structure
        parsed = json.loads(json_str)
        assert parsed == {
            "category": "helpful",
            "confidence": 0.9,
            "reasoning": "The agent helped by doing ABC",
        }

        # Verify citation points to "ABC"
        assert len(citations) == 1
        cite = citations[0]
        assert json_str[cite["start_idx"] : cite["end_idx"]] == "ABC"

    def test_multiple_citation_fields(self):
        """Schema with multiple fields that have citations."""
        output = {
            "summary": {
                "text": "Short summary",
                "citations": [
                    {"start_idx": 0, "end_idx": 5, "transcript_id": "t1", "turn_number": 0}
                ],
            },
            "analysis": {
                "text": "Detailed analysis here",
                "citations": [
                    {"start_idx": 9, "end_idx": 17, "transcript_id": "t2", "turn_number": 3}
                ],
            },
        }

        json_str, citations = transform_output_for_chat(output)

        # Verify both texts are in the JSON
        parsed = json.loads(json_str)
        assert parsed["summary"] == "Short summary"
        assert parsed["analysis"] == "Detailed analysis here"

        # Verify both citations are adjusted correctly
        assert len(citations) == 2

        # Find which citation is which by checking transcript_id
        summary_cite = next(c for c in citations if c["transcript_id"] == "t1")
        analysis_cite = next(c for c in citations if c["transcript_id"] == "t2")

        assert json_str[summary_cite["start_idx"] : summary_cite["end_idx"]] == "Short"
        assert json_str[analysis_cite["start_idx"] : analysis_cite["end_idx"]] == "analysis"

    def test_nested_citation_field(self):
        """Citation field nested inside another object."""
        output = {
            "result": {
                "verdict": "pass",
                "explanation": {
                    "text": "It worked",
                    "citations": [
                        {"start_idx": 3, "end_idx": 9, "transcript_id": "t1", "turn_number": 0}
                    ],
                },
            }
        }

        json_str, citations = transform_output_for_chat(output)

        # Verify structure
        parsed = json.loads(json_str)
        assert parsed["result"]["explanation"] == "It worked"

        # Verify citation points to "worked"
        assert len(citations) == 1
        assert json_str[citations[0]["start_idx"] : citations[0]["end_idx"]] == "worked"

    def test_citation_field_in_array(self):
        """Citation fields inside an array."""
        output = {
            "items": [
                {"text": "First item", "citations": [{"start_idx": 0, "end_idx": 5, "id": "c1"}]},
                {"text": "Second item", "citations": [{"start_idx": 0, "end_idx": 6, "id": "c2"}]},
            ]
        }

        json_str, citations = transform_output_for_chat(output)

        # Verify structure
        parsed = json.loads(json_str)
        assert parsed["items"] == ["First item", "Second item"]

        # Verify citations
        assert len(citations) == 2
        c1 = next(c for c in citations if c["id"] == "c1")
        c2 = next(c for c in citations if c["id"] == "c2")
        assert json_str[c1["start_idx"] : c1["end_idx"]] == "First"
        assert json_str[c2["start_idx"] : c2["end_idx"]] == "Second"

    def test_text_with_special_characters(self):
        """Text containing characters that need JSON escaping."""
        output = {
            "output": {
                "text": 'The agent said "hello"',
                "citations": [
                    {"start_idx": 16, "end_idx": 21, "transcript_id": "t1", "turn_number": 0}
                ],
            }
        }

        json_str, citations = transform_output_for_chat(output)

        # The citation should point to "hello" in the escaped string
        assert len(citations) == 1
        cite = citations[0]

        # In the JSON, "hello" appears as hello (the quotes around it are escaped)
        highlighted = json_str[cite["start_idx"] : cite["end_idx"]]
        assert highlighted == "hello"

    def test_text_with_newlines(self):
        """Text containing newlines that need JSON escaping."""
        output = {
            "output": {
                "text": "line1\nline2",
                "citations": [
                    {"start_idx": 6, "end_idx": 11, "transcript_id": "t1", "turn_number": 0}
                ],
            }
        }

        json_str, citations = transform_output_for_chat(output)

        # Citation should point to "line2" in escaped form
        assert len(citations) == 1
        cite = citations[0]
        assert json_str[cite["start_idx"] : cite["end_idx"]] == "line2"

    def test_no_citation_fields(self):
        """Output with no citation fields should just stringify."""
        output = {"category": "neutral", "score": 5}

        json_str, citations = transform_output_for_chat(output)

        assert json.loads(json_str) == output
        assert citations == []

    def test_empty_citations_list(self):
        """Citation field with empty citations list."""
        output: dict[str, dict[str, object]] = {
            "output": {
                "text": "Some text",
                "citations": [],
            }
        }

        json_str, citations = transform_output_for_chat(output)  # type: ignore[arg-type]

        parsed = json.loads(json_str)
        assert parsed == {"output": "Some text"}
        assert citations == []

    def test_preserves_citation_metadata(self):
        """All citation metadata should be preserved."""
        output = {
            "output": {
                "text": "Test",
                "citations": [
                    {
                        "start_idx": 0,
                        "end_idx": 4,
                        "transcript_id": "abc123",
                        "turn_number": 7,
                        "agent_run_id": "run456",
                        "custom_field": "preserved",
                    }
                ],
            }
        }

        _, citations = transform_output_for_chat(output)

        assert len(citations) == 1
        cite = citations[0]
        assert cite["transcript_id"] == "abc123"
        assert cite["turn_number"] == 7
        assert cite["agent_run_id"] == "run456"
        assert cite["custom_field"] == "preserved"

    def test_duplicate_text_values(self):
        """Handle case where same text appears multiple times."""
        output = {
            "field1": {
                "text": "same",
                "citations": [{"start_idx": 0, "end_idx": 4, "id": "c1"}],
            },
            "field2": {
                "text": "same",
                "citations": [{"start_idx": 0, "end_idx": 4, "id": "c2"}],
            },
        }

        json_str, citations = transform_output_for_chat(output)

        # Both citations should be present and point to different occurrences
        assert len(citations) == 2

        # Both should highlight "same"
        for cite in citations:
            assert json_str[cite["start_idx"] : cite["end_idx"]] == "same"

        # They should point to different positions
        positions = {cite["start_idx"] for cite in citations}
        assert len(positions) == 2  # Two different positions
