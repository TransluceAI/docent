import re
from dataclasses import dataclass

from pydantic import BaseModel


@dataclass
class ParsedCitation:
    """Represents a parsed citation before conversion to full Citation object."""

    transcript_idx: int | None
    block_idx: int | None
    metadata_key: str | None = None
    start_pattern: str | None = None


class Citation(BaseModel):
    start_idx: int
    end_idx: int
    agent_run_idx: int | None = None
    transcript_idx: int | None = None
    block_idx: int | None = None
    action_unit_idx: int | None = None
    metadata_key: str | None = None
    start_pattern: str | None = None


RANGE_BEGIN = "<RANGE>"
RANGE_END = "</RANGE>"

_SINGLE_RE = re.compile(r"T(\d+)B(\d+)")
_METADATA_RE = re.compile(r"^M\.([^:]+)$")  # [M.key]
_TRANSCRIPT_METADATA_RE = re.compile(r"^T(\d+)M\.([^:]+)$")  # [T0M.key]
_MESSAGE_METADATA_RE = re.compile(r"^T(\d+)B(\d+)M\.([^:]+)$")  # [T0B1M.key]
_RANGE_CONTENT_RE = re.compile(r":\s*" + re.escape(RANGE_BEGIN) + r".*?" + re.escape(RANGE_END))


def _extract_range_pattern(range_part: str) -> str | None:
    start_pattern: str | None = None

    if RANGE_BEGIN in range_part and RANGE_END in range_part:
        range_begin_idx = range_part.find(RANGE_BEGIN)
        range_end_idx = range_part.find(RANGE_END)
        if range_begin_idx != -1 and range_end_idx != -1:
            range_content = range_part[range_begin_idx + len(RANGE_BEGIN) : range_end_idx]
            start_pattern = range_content if range_content else None

    return start_pattern


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


def parse_single_citation(part: str) -> ParsedCitation | None:
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
    start_pattern: str | None = None
    citation_part = token
    if ":" in token:
        left, right = token.split(":", 1)
        citation_part = left.strip()
        start_pattern = _extract_range_pattern(right)

    # Try matches in order of specificity
    # 1) Message metadata [T0B0M.key]
    m = _MESSAGE_METADATA_RE.match(citation_part)
    if m:
        transcript_idx = int(m.group(1))
        block_idx = int(m.group(2))
        metadata_key = m.group(3)
        # Disallow nested keys like status.code per instruction
        if "." in metadata_key:
            return None
        return ParsedCitation(
            transcript_idx=transcript_idx,
            block_idx=block_idx,
            metadata_key=metadata_key,
            start_pattern=start_pattern,
        )

    # 2) Transcript metadata [T0M.key]
    m = _TRANSCRIPT_METADATA_RE.match(citation_part)
    if m:
        transcript_idx = int(m.group(1))
        metadata_key = m.group(2)
        if "." in metadata_key:
            return None
        return ParsedCitation(
            transcript_idx=transcript_idx,
            block_idx=None,
            metadata_key=metadata_key,
            start_pattern=start_pattern,
        )

    # 3) Agent run metadata [M.key]
    m = _METADATA_RE.match(citation_part)
    if m:
        metadata_key = m.group(1)
        if "." in metadata_key:
            return None
        return ParsedCitation(
            transcript_idx=None,
            block_idx=None,
            metadata_key=metadata_key,
            start_pattern=start_pattern,
        )

    # 4) Regular transcript block [T0B0]
    m = _SINGLE_RE.match(citation_part)
    if m:
        transcript_idx = int(m.group(1))
        block_idx = int(m.group(2))
        return ParsedCitation(
            transcript_idx=transcript_idx, block_idx=block_idx, start_pattern=start_pattern
        )

    return None


def parse_citations(text: str) -> tuple[str, list[Citation]]:
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
    citations: list[Citation] = []
    cleaned_text = ""

    bracket_matches = scan_brackets(text)

    last_end = 0
    for start, end, bracket_content in bracket_matches:
        # Append non-bracket text segment as-is
        cleaned_text += text[last_end:start]

        # Parse a single citation token inside the bracket
        parsed = parse_single_citation(bracket_content)
        if parsed:
            # Create appropriate replacement text based on citation type
            if parsed.metadata_key:
                if parsed.transcript_idx is None:
                    # Agent run metadata [M.key]
                    replacement = "run metadata"
                elif parsed.block_idx is None:
                    # Transcript metadata [T0M.key]
                    replacement = f"T{parsed.transcript_idx}"
                else:
                    # Message metadata [T0B1M.key]
                    replacement = f"T{parsed.transcript_idx}B{parsed.block_idx}"
            else:
                # Regular transcript block [T0B1]
                replacement = f"T{parsed.transcript_idx}B{parsed.block_idx}"

            # Current absolute start position for this replacement in the cleaned text
            start_idx = len(cleaned_text)
            end_idx = start_idx + len(replacement)
            citations.append(
                Citation(
                    start_idx=start_idx,
                    end_idx=end_idx,
                    agent_run_idx=None,
                    transcript_idx=parsed.transcript_idx,
                    block_idx=parsed.block_idx,
                    action_unit_idx=None,
                    metadata_key=parsed.metadata_key,
                    start_pattern=parsed.start_pattern,
                )
            )
            cleaned_text += replacement
        last_end = end

    # Append any remaining tail after the last bracket
    cleaned_text += text[last_end:]

    return cleaned_text, citations
