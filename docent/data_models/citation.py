import re
from typing import TypedDict


class Citation(TypedDict):
    start_idx: int
    end_idx: int
    agent_run_idx: int | None
    transcript_idx: int | None
    block_idx: int
    action_unit_idx: int | None


def parse_citations_single_run(text: str) -> list[Citation]:
    """
    Parse citations from text in the format described by SINGLE_BLOCK_CITE_INSTRUCTION.

    Supported formats:
    - Single block: [T<key>B<idx>]
    - Multiple blocks: [T<key1>B<idx1>, T<key2>B<idx2>, ...]
    - Dash-separated blocks: [T<key1>B<idx1>-T<key2>B<idx2>]

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
            # Check if this part contains a dash (range citation)
            if "-" in part:
                # Split by dash and process each sub-part
                dash_parts = [dash_part.strip() for dash_part in part.split("-")]
                for dash_part in dash_parts:
                    # Check for single block citation: T<key>B<idx>
                    single_match = re.match(r"T(\d+)B(\d+)", dash_part)
                    if single_match:
                        transcript_idx = int(single_match.group(1))
                        block_idx = int(single_match.group(2))

                        # Find position within the original text
                        citation_text = f"T{transcript_idx}B{block_idx}"
                        part_pos_in_content = bracket_content.find(dash_part)
                        ref_pos = content_start_pos + part_pos_in_content
                        ref_end = ref_pos + len(citation_text)

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
                                    agent_run_idx=None,
                                    transcript_idx=transcript_idx,
                                    block_idx=block_idx,
                                    action_unit_idx=None,
                                )
                            )
            else:
                # Check for single block citation: T<key>B<idx>
                single_match = re.match(r"T(\d+)B(\d+)", part)
                if single_match:
                    transcript_idx = int(single_match.group(1))
                    block_idx = int(single_match.group(2))

                    # Find position within the original text
                    citation_text = f"T{transcript_idx}B{block_idx}"
                    part_pos_in_content = bracket_content.find(part)
                    ref_pos = content_start_pos + part_pos_in_content
                    ref_end = ref_pos + len(citation_text)

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
                                agent_run_idx=None,
                                transcript_idx=transcript_idx,
                                block_idx=block_idx,
                                action_unit_idx=None,
                            )
                        )

    return citations


def parse_citations_multi_run(text: str) -> list[Citation]:
    """
    Parse citations from text in the format described by MULTI_BLOCK_CITE_INSTRUCTION.

    Supported formats:
    - Single block in transcript: [R<idx>T<key>B<idx>] or ([R<idx>T<key>B<idx>])
    - Multiple blocks: [R<idx1>T<key1>B<idx1>][R<idx2>T<key2>B<idx2>]
    - Comma-separated blocks: [R<idx1>T<key1>B<idx1>, R<idx2>T<key2>B<idx2>, ...]
    - Dash-separated blocks: [R<idx1>T<key1>B<idx1>-R<idx2>T<key2>B<idx2>]

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
    single_pattern = r"R(\d+)T(\d+)B(\d+)"

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
                # Check if this item contains a dash (range citation)
                if "-" in item:
                    # Split by dash and process each sub-item
                    dash_items = [dash_item.strip() for dash_item in item.split("-")]
                    for dash_item in dash_items:
                        # Check for single citation
                        single_match = re.match(single_pattern, dash_item)
                        if single_match:
                            agent_run_idx = int(single_match.group(1))
                            transcript_idx = int(single_match.group(2))
                            block_idx = int(single_match.group(3))

                            # Calculate position in the original text
                            citation_text = f"R{agent_run_idx}T{transcript_idx}B{block_idx}"
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
                                        agent_run_idx=agent_run_idx,
                                        transcript_idx=transcript_idx,
                                        block_idx=block_idx,
                                        action_unit_idx=None,
                                    )
                                )
                else:
                    # Check for single citation
                    single_match = re.match(single_pattern, item)
                    if single_match:
                        agent_run_idx = int(single_match.group(1))
                        transcript_idx = int(single_match.group(2))
                        block_idx = int(single_match.group(3))

                        # Calculate position in the original text
                        citation_text = f"R{agent_run_idx}T{transcript_idx}B{block_idx}"
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
                                    agent_run_idx=agent_run_idx,
                                    transcript_idx=transcript_idx,
                                    block_idx=block_idx,
                                    action_unit_idx=None,
                                )
                            )

    return citations
