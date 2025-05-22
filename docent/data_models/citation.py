import re
from typing import TypedDict


class Citation(TypedDict):
    start_idx: int
    end_idx: int
    block_idx: int
    transcript_idx: int | None
    action_unit_idx: int | None


def parse_citations_single_transcript(text: str) -> list[Citation]:
    """
    Parse citations from text in the format described by SINGLE_BLOCK_CITE_INSTRUCTION.

    Supported formats:
    - Single block: [B<idx>]
    - Multiple blocks: [B<idx1>, B<idx2>, ...]
    - Range of blocks: [B<idx1>-B<idx2>] or [B<idx1>–B<idx2>]

    Args:
        text: The text to parse citations from

    Returns:
        A list of Citation objects with start_idx and end_idx representing
        the character positions in the text (excluding brackets)
    """
    citations: list[Citation] = []

    # Find all bracketed content first
    bracket_pattern = r"\[(.*?)\]"
    bracket_matches = re.finditer(bracket_pattern, text)

    for bracket_match in bracket_matches:
        bracket_content = bracket_match.group(1)
        # Starting position of the bracket content (excluding '[')
        content_start_pos = bracket_match.start() + 1

        # Split by commas if present
        parts = [part.strip() for part in bracket_content.split(",")]

        for part in parts:
            # Check for range citation: B<idx1>-B<idx2> or B<idx1>–B<idx2>
            range_match = re.match(r"B(\d+)[–\-]B(\d+)", part)
            if range_match:
                start_block = int(range_match.group(1))
                end_block = int(range_match.group(2))

                # Find positions within the original text
                first_ref_pos = content_start_pos + part.find(f"B{start_block}")
                first_ref_end = first_ref_pos + len(f"B{start_block}")

                second_ref_pos = content_start_pos + part.find(f"B{end_block}")
                second_ref_end = second_ref_pos + len(f"B{end_block}")

                # Add citation for first block
                citations.append(
                    Citation(
                        start_idx=first_ref_pos,
                        end_idx=first_ref_end,
                        block_idx=start_block,
                        transcript_idx=None,
                        action_unit_idx=None,
                    )
                )

                # Add citation for second block
                citations.append(
                    Citation(
                        start_idx=second_ref_pos,
                        end_idx=second_ref_end,
                        block_idx=end_block,
                        transcript_idx=None,
                        action_unit_idx=None,
                    )
                )
            else:
                # Check for single block citation: B<idx>
                single_match = re.match(r"B(\d+)", part)
                if single_match:
                    block_idx = int(single_match.group(1))

                    # Find position within the original text
                    part_pos_in_content = bracket_content.find(part)
                    ref_pos = content_start_pos + part_pos_in_content
                    ref_end = ref_pos + len(f"B{block_idx}")

                    # Check if this citation overlaps with any existing citation
                    if not any(
                        citation["start_idx"] <= ref_pos < citation["end_idx"]
                        or citation["start_idx"] < ref_end <= citation["end_idx"]
                        for citation in citations
                    ):
                        citations.append(
                            Citation(
                                start_idx=ref_pos,
                                end_idx=ref_end,
                                block_idx=block_idx,
                                transcript_idx=None,
                                action_unit_idx=None,
                            )
                        )

    return citations


def parse_citations_multi_transcript(text: str) -> list[Citation]:
    """
    Parse citations from text in the format described by MULTI_BLOCK_CITE_INSTRUCTION.

    Supported formats:
    - Single block in transcript: [T<tidx>B<idx>] or ([T<tidx>B<idx>])
    - Multiple blocks: [T<tidx1>B<idx1>][T<tidx2>B<idx2>]
    - Comma-separated blocks: [T<tidx1>B<idx1>, T<tidx2>B<idx2>, ...]
    - Range of blocks: [T<tidx1>B<idx1>-T<tidx2>B<idx2>] or [T<tidx1>B<idx1>–T<tidx2>B<idx2>]
      (supports both hyphen and en dash)

    Args:
        text: The text to parse citations from

    Returns:
        A list of Citation objects with start_idx and end_idx representing
        the character positions in the text (excluding brackets)
    """
    citations: list[Citation] = []

    # Find all content within brackets - this handles nested brackets too
    bracket_pattern = r"\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]"
    # Also handle optional parentheses around the brackets
    paren_bracket_pattern = r"\(\[([^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*)\]\)"

    # Single citation pattern
    single_pattern = r"T(\d+)B(\d+)"
    # Range citation pattern with hyphen or en dash
    range_pattern = r"T(\d+)B(\d+)[–\-]T(\d+)B(\d+)"

    # Find all bracket matches
    for pattern in [bracket_pattern, paren_bracket_pattern]:
        matches = re.finditer(pattern, text)
        for match in matches:
            # Get the content inside brackets
            if pattern == bracket_pattern:
                content = match.group(1)
                start_pos = match.start() + 1  # +1 to skip the opening bracket
            else:
                content = match.group(1)
                start_pos = match.start() + 2  # +2 to skip the opening parenthesis and bracket

            # Split by comma if present
            items = [item.strip() for item in content.split(",")]

            for item in items:
                # Check for range citation first
                range_match = re.match(range_pattern, item)
                if range_match:
                    start_transcript = int(range_match.group(1))
                    start_block = int(range_match.group(2))
                    end_transcript = int(range_match.group(3))
                    end_block = int(range_match.group(4))

                    # Calculate positions in the original text
                    first_citation_text = f"T{start_transcript}B{start_block}"
                    first_citation_start = text.find(first_citation_text, start_pos)
                    first_citation_end = first_citation_start + len(first_citation_text)

                    second_citation_text = f"T{end_transcript}B{end_block}"
                    second_citation_start = text.find(second_citation_text, first_citation_end)
                    second_citation_end = second_citation_start + len(second_citation_text)

                    # Add citations
                    citations.append(
                        Citation(
                            start_idx=first_citation_start,
                            end_idx=first_citation_end,
                            block_idx=start_block,
                            transcript_idx=start_transcript,
                            action_unit_idx=None,
                        )
                    )

                    citations.append(
                        Citation(
                            start_idx=second_citation_start,
                            end_idx=second_citation_end,
                            block_idx=end_block,
                            transcript_idx=end_transcript,
                            action_unit_idx=None,
                        )
                    )
                else:
                    # Check for single citation
                    single_match = re.match(single_pattern, item)
                    if single_match:
                        transcript_idx = int(single_match.group(1))
                        block_idx = int(single_match.group(2))

                        # Calculate position in the original text
                        citation_text = f"T{transcript_idx}B{block_idx}"
                        citation_start = text.find(citation_text, start_pos)
                        citation_end = citation_start + len(citation_text)

                        # Move start_pos for the next item if there are more items
                        start_pos = citation_end

                        # Avoid duplicate citations
                        if not any(
                            citation["start_idx"] == citation_start
                            and citation["end_idx"] == citation_end
                            for citation in citations
                        ):
                            citations.append(
                                Citation(
                                    start_idx=citation_start,
                                    end_idx=citation_end,
                                    block_idx=block_idx,
                                    transcript_idx=transcript_idx,
                                    action_unit_idx=None,
                                )
                            )

    return citations
