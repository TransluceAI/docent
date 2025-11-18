from typing import Annotated, Literal, Union

from pydantic import BaseModel, Discriminator


class CitationTargetTextRange(BaseModel):
    start_pattern: str | None = None
    end_pattern: str | None = None


class ResolvedCitationItem(BaseModel):
    pass


class CitationTarget(BaseModel):
    item: "ResolvedCitationItemUnion"
    text_range: CitationTargetTextRange | None = None


class ParsedCitation(BaseModel):
    start_idx: int
    end_idx: int
    item_alias: str
    text_range: CitationTargetTextRange | None = None


class InlineCitation(BaseModel):
    start_idx: int
    end_idx: int
    target: CitationTarget


class AgentRunMetadataItem(ResolvedCitationItem):
    item_type: Literal["agent_run_metadata"] = "agent_run_metadata"
    agent_run_id: str
    collection_id: str
    metadata_key: str


class TranscriptMetadataItem(ResolvedCitationItem):
    item_type: Literal["transcript_metadata"] = "transcript_metadata"
    agent_run_id: str
    collection_id: str
    transcript_id: str
    metadata_key: str


class TranscriptBlockMetadataItem(ResolvedCitationItem):
    item_type: Literal["block_metadata"] = "block_metadata"
    agent_run_id: str
    collection_id: str
    transcript_id: str
    block_idx: int
    metadata_key: str


class TranscriptBlockContentItem(ResolvedCitationItem):
    item_type: Literal["block_content"] = "block_content"
    agent_run_id: str
    collection_id: str
    transcript_id: str
    block_idx: int


ResolvedCitationItemUnion = Annotated[
    Union[
        AgentRunMetadataItem,
        TranscriptMetadataItem,
        TranscriptBlockMetadataItem,
        TranscriptBlockContentItem,
    ],
    Discriminator("item_type"),
]

RANGE_BEGIN = "<RANGE>"
RANGE_END = "</RANGE>"


def scan_brackets(text: str) -> list[tuple[int, int, str]]:
    """Scan text for bracketed segments, respecting RANGE markers and nested brackets.

    Returns a list of (start_index, end_index_exclusive, inner_content).
    """
    matches: list[tuple[int, int, str]] = []
    i = 0
    while i < len(text):
        if text[i] == "[":
            start = i
            bracket_count = 1
            j = i + 1
            in_range = False

            while j < len(text) and bracket_count > 0:
                if text[j : j + len(RANGE_BEGIN)] == RANGE_BEGIN:
                    in_range = True
                elif text[j : j + len(RANGE_END)] == RANGE_END:
                    in_range = False
                elif text[j] == "[" and not in_range:
                    bracket_count += 1
                elif text[j] == "]" and not in_range:
                    bracket_count -= 1
                j += 1

            if bracket_count == 0:
                end_exclusive = j
                bracket_content = text[start + 1 : end_exclusive - 1]
                matches.append((start, end_exclusive, bracket_content))
                i = j
            else:
                i += 1
        else:
            i += 1
    return matches


def _extract_range_pattern(range_part: str) -> CitationTargetTextRange | None:
    if RANGE_BEGIN in range_part and RANGE_END in range_part:
        range_begin_idx = range_part.find(RANGE_BEGIN)
        range_end_idx = range_part.find(RANGE_END)
        if range_begin_idx != -1 and range_end_idx != -1:
            range_content = range_part[range_begin_idx + len(RANGE_BEGIN) : range_end_idx]
            start_pattern = range_content if range_content else None
            return CitationTargetTextRange(start_pattern=start_pattern)

    return None


def parse_single_citation(part: str) -> tuple[str, CitationTargetTextRange | None] | None:
    """
    Parse a single citation token inside a bracket and return its components.

    Returns ParsedCitation or None if invalid.
    For metadata citations, transcript_idx may be None (for agent run metadata).
    Supports optional text range for all valid citation kinds.
    """
    token = part.strip()
    if not token:
        return None

    # Extract optional range part
    item_alias = token
    text_range: CitationTargetTextRange | None = None
    if ":" in token:
        left, right = token.split(":", 1)
        item_alias = left.strip()
        text_range = _extract_range_pattern(right)

    return item_alias, text_range


def parse_citations(text: str) -> tuple[str, list[ParsedCitation]]:
    """
    Parse citations from text in the format described by TEXT_RANGE_CITE_INSTRUCTION.

    Supported formats:
    - Single block: [T<key>B<idx>]
    - Text range with start pattern: [T<key>B<idx>:<RANGE>start_pattern</RANGE>]
    - Agent run metadata: [M.key]
    - Transcript metadata: [T<key>M.key]
    - Message metadata: [T<key>B<idx>M.key]
    - Message metadata with text range: [T<key>B<idx>M.key:<RANGE>start_pattern</RANGE>]

    Args:
        text: The text to parse citations from

    Returns:
        A tuple of (cleaned_text, citations) where cleaned_text has brackets and range markers removed
        and citations have start_idx and end_idx representing character positions
        in the cleaned text
    """
    citations: list[ParsedCitation] = []

    bracket_matches = scan_brackets(text)

    for start, end, bracket_content in bracket_matches:
        # Parse a single citation token inside the bracket
        parsed = parse_single_citation(bracket_content)
        if not parsed:
            continue
        label, text_range = parsed

        citations.append(
            ParsedCitation(start_idx=start, end_idx=end, item_alias=label, text_range=text_range)
        )

    # We're not cleaning the text right now but may do that later
    return text, citations
