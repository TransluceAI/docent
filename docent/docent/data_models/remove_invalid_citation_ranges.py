import json
import re

from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import Citation, parse_single_citation, scan_brackets
from docent.data_models.transcript import format_chat_message


def build_whitespace_flexible_regex(pattern: str) -> re.Pattern[str]:
    """Build regex that is flexible with whitespace matching."""
    out = ""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch.isspace():
            # Skip all consecutive whitespace
            while i < len(pattern) and pattern[i].isspace():
                i += 1
            out += r"\s+"
            continue
        out += re.escape(ch)
        i += 1
    return re.compile(out, re.DOTALL)


def find_citation_matches_in_text(text: str, start_pattern: str) -> list[tuple[int, int]]:
    """
    Find all matches of a citation pattern in text.

    Args:
        text: The text to search in
        start_pattern: The pattern to search for

    Returns:
        List of (start_index, end_index) tuples for matches
    """
    if not start_pattern:
        return []

    try:
        regex = build_whitespace_flexible_regex(start_pattern)
        matches: list[tuple[int, int]] = []

        for match in regex.finditer(text):
            if match.group().strip():  # Only count non-empty matches
                matches.append((match.start(), match.end()))

        return matches

    except re.error:
        return []


def get_transcript_text_for_citation(agent_run: AgentRun, citation: Citation) -> str | None:
    """
    Get the text content of a specific transcript block (or transcript/run metadata) from an AgentRun,
    using the same formatting as shown to LLMs via format_chat_message.

    Args:
        agent_run: The agent run containing transcript data
        citation: Citation with transcript_idx and block_idx

    Returns:
        Text content of the specified block (including tool calls), or None if not found
    """
    try:
        if citation.transcript_idx is None:
            # At the run level, can only cite metadata
            if citation.metadata_key is not None:
                return json.dumps(agent_run.metadata.get(citation.metadata_key))
            return None

        transcript_id = agent_run.get_transcript_ids_ordered()[citation.transcript_idx]
        transcript = agent_run.transcript_dict[transcript_id]

        if citation.block_idx is None:
            # At the transcript level, can only cite metadata
            if citation.metadata_key is not None:
                return json.dumps(transcript.metadata.get(citation.metadata_key))
            return None

        message = transcript.messages[citation.block_idx]

        # At the message level, can cite metadata or content
        if citation.metadata_key is not None:
            return json.dumps(message.metadata.get(citation.metadata_key))

        # Use the same formatting function that generates content for LLMs
        # This ensures consistent formatting between citation validation and LLM serialization
        return format_chat_message(
            message, citation.block_idx, citation.transcript_idx, citation.agent_run_idx
        )

    except (KeyError, IndexError, AttributeError):
        return None


def validate_citation_text_range(agent_run: AgentRun, citation: Citation) -> bool:
    """
    Validate that a citation's text range exists in the referenced transcript.

    Args:
        agent_run: The agent run containing transcript data
        citation: Citation to validate

    Returns:
        True if the citation's text range exists in the transcript, False otherwise
    """
    if not citation.start_pattern:
        # Nothing to validate
        return True
    if citation.metadata_key is not None:
        # We don't need to remove invalid metadata citation ranges
        return True

    text = get_transcript_text_for_citation(agent_run, citation)
    if text is None:
        return False

    matches = find_citation_matches_in_text(text, citation.start_pattern)

    return len(matches) > 0


def remove_invalid_citation_ranges(text: str, agent_run: AgentRun) -> str:
    """
    Remove invalid citation ranges from chat message/judge result. We do this as a separate step before normal citation parsing.
    Normal citation parsing happens every time we load chat/results from db,
    but invalid ranges should never make it to the db.

    Args:
        text: Original text containing citations
        agent_run: Agent run with transcript data

    Returns:
        Tuple of (cleaned_text, valid_citations)
    """
    # Find all bracket positions in the original text
    bracket_matches = scan_brackets(text)
    citations: list[Citation] = []

    for start, end, bracket_content in bracket_matches:
        # Parse this bracket content to get citation info
        parsed = parse_single_citation(bracket_content)
        if parsed:
            # The citation spans from start to end in the original text
            citation = Citation(
                start_idx=start,
                end_idx=end,
                agent_run_idx=None,
                transcript_idx=parsed.transcript_idx,
                block_idx=parsed.block_idx,
                action_unit_idx=None,
                metadata_key=parsed.metadata_key,
                start_pattern=parsed.start_pattern,
            )
            citations.append(citation)

    # Filter to only citations with text ranges that need validation
    citations_to_validate = [c for c in citations if c.start_pattern]

    # Sort citations by start_idx in reverse order to avoid index shifting issues
    sorted_citations = sorted(citations_to_validate, key=lambda c: c.start_idx, reverse=True)

    invalid_citations: list[Citation] = [
        c for c in sorted_citations if not validate_citation_text_range(agent_run, c)
    ]

    # Remove invalid text ranges from citations in the original text
    modified_text = text
    for citation in invalid_citations:
        citation_without_range = f"[T{citation.transcript_idx}B{citation.block_idx}]"
        before = modified_text[: citation.start_idx]
        after = modified_text[citation.end_idx :]
        modified_text = before + citation_without_range + after
    return modified_text
