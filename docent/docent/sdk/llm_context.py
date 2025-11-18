import json
import re
import sys
import textwrap
from typing import Any

from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import (
    AgentRunMetadataItem,
    CitationTarget,
    InlineCitation,
    ResolvedCitationItemUnion,
    TranscriptBlockContentItem,
    TranscriptBlockMetadataItem,
    TranscriptMetadataItem,
    parse_citations,
)
from docent.data_models.formatted_objects import FormattedAgentRun, FormattedTranscript
from docent.data_models.transcript import Transcript, format_chat_message

RANGE_BEGIN = "<RANGE>"
RANGE_END = "</RANGE>"

LLMContextItem = AgentRun | Transcript

_SINGLE_RE = re.compile(r"T(\d+)B(\d+)")
_AGENT_RUN_METADATA_RE = re.compile(r"^R(\d+)M\.([^:]+)$")  # [R0M.key]
_TRANSCRIPT_METADATA_RE = re.compile(r"^T(\d+)M\.([^:]+)$")  # [T0M.key]
_MESSAGE_METADATA_RE = re.compile(r"^T(\d+)B(\d+)M\.([^:]+)$")  # [T0B1M.key]
_RANGE_CONTENT_RE = re.compile(r":\s*" + re.escape(RANGE_BEGIN) + r".*?" + re.escape(RANGE_END))


class LLMContext:
    """Manages a collection of objects (agent runs, transcripts) for LLM consumption.

    This class provides:
    - Assignment of local IDs (T0, T1, R0, etc.) for citations
    - Serialization for database storage
    - Conversion to LLM-ready string format
    - Citation resolution mapping local IDs back to database UUIDs

    Example usage:
        context = LLMContext()
        context.add(agent_run1)
        context.add(agent_run2)

        # Get string representation for LLM
        llm_input = context.to_str()

        # Get system message with citation instructions
        system_msg = context.get_system_message()

        # Serialize for database storage
        serialized = context.to_dict()
    """

    def __init__(self, items: list[LLMContextItem] | None = None):
        self.root_items: list[str] = []

        self.transcript_aliases: dict[int, Transcript] = {}
        self.agent_run_aliases: dict[int, AgentRun] = {}

        self.agent_run_collection_ids: dict[str, str] = {}  # agent_run_id -> collection_id
        self.transcript_to_agent_run: dict[str, str] = {}  # transcript_id -> agent_run_id

        if items is not None:
            for item in items:
                self.add(item)

    def add(self, item: LLMContextItem) -> None:
        """Add an object to the context.

        Accepts AgentRun, Transcript, FormattedAgentRun, or FormattedTranscript.
        """
        alias = self._create_alias(item)

        if isinstance(item, AgentRun):
            # Assign aliases in canonical tree order
            t_ids_ordered = item.get_transcript_ids_ordered(full_tree=False)
            for t_id in t_ids_ordered:
                transcript = item.transcript_dict[t_id]
                self._create_alias(transcript)
                self.transcript_to_agent_run[t_id] = item.id

        self.root_items.append(alias)

    def _create_alias(self, item: LLMContextItem) -> str:
        if isinstance(item, AgentRun):
            idx = len(self.agent_run_aliases)
            alias = "R" + str(idx)
            self.agent_run_aliases[idx] = item
        elif isinstance(item, Transcript):  # type: ignore
            idx = len(self.transcript_aliases)
            alias = "T" + str(idx)
            self.transcript_aliases[idx] = item
        else:
            raise ValueError(f"Unknown item type: {type(item)}")
        return alias

    def get_item_by_alias(self, alias: str) -> LLMContextItem:
        if not alias:
            raise ValueError("Alias cannot be empty")

        prefix = alias[0]
        try:
            idx = int(alias[1:])
        except ValueError as exc:
            raise ValueError(f"Invalid alias format: {alias}") from exc

        if prefix == "R":
            if idx not in self.agent_run_aliases:
                raise ValueError(f"Unknown agent run alias: {alias}")
            return self.agent_run_aliases[idx]

        if prefix == "T":
            if idx not in self.transcript_aliases:
                raise ValueError(f"Unknown transcript alias: {alias}")
            return self.transcript_aliases[idx]

        raise ValueError(f"Unknown alias type: {alias}")

    def to_str(self, token_limit: int = sys.maxsize) -> str:
        """Format all objects for LLM consumption with proper headers.

        Args:
            token_limit: Maximum tokens for the output (default: no limit)

        Returns:
            Formatted string with all objects and their local IDs
        """
        sections: list[str] = []

        for alias in self.root_items:
            item = self.get_item_by_alias(alias)
            # Render each transcript with its global index
            if isinstance(item, Transcript):
                transcript_text = item.to_text_new(alias)
                sections.append(transcript_text)
            elif isinstance(item, AgentRun):  # type: ignore
                id_to_idx_map = {t.id: i for i, t in self.transcript_aliases.items()}
                agent_run_text = item.to_text_new(alias, t_idx_map=id_to_idx_map)
                sections.append(agent_run_text)
            else:
                raise ValueError(f"Unknown item type: {type(item)}")

        return "\n\n".join(sections)

    def get_system_message(self) -> str:
        """Generate a system prompt with citation instructions for multi-object context.

        Returns:
            System message string with instructions on how to cite objects
        """

        context_description = f"You are a helpful assistant that specializes in analyzing transcripts of AI agent behavior."

        citation_instructions = textwrap.dedent(
            f"""
            Anytime you quote an item that has an ID, or make any claim about such an item, add an inline citation.

            To cite an item, write the item ID in brackets. For example, to cite T0B1, write [T0B1].

            You may cite a specific range of text within an item. Use {RANGE_BEGIN} and {RANGE_END} to mark the specific range of text. Add it after the item ID separated by a colon. For example, to cite the part of T0B1 where the agent says "I understand the task", write [T0B1:{RANGE_BEGIN}I understand the task{RANGE_END}]. Citations must follow this exact format. The markers {RANGE_BEGIN} and {RANGE_END} must be used ONLY inside the brackets of a citation.

            - When citing metadata (that is, an item whose ID ends with M), you must cite a top-level key with dot syntax. For example, for agent run 0 metadata: [R0M.task_description].
            - You may not cite nested keys. For example, [T0B1M.status.code] is invalid.
            - Within a top-level metadata key you may cite a range of text that appears in the value. For example, [T0B1M.status:{RANGE_BEGIN}\"running\":false{RANGE_END}].

            Important notes:
            - You must include the full content of the text range {RANGE_BEGIN} and {RANGE_END}, EXACTLY as it appears in the transcript, word-for-word, including any markers or punctuation that appear in the middle of the text.
            - Citations must be as specific as possible. This means you should usually cite a specific text range.
            - A citation is not a quote. For brevity, text ranges will not be rendered inline. The user will have to click on the citation to see the full text range.
            - Citations are self-contained. Do NOT label them as citation or evidence. Just insert the citation by itself at the appropriate place in the text.
            - Citations must come immediately after the part of a claim that they support. This may be in the middle of a sentence.
            - Each pair of brackets must contain only one citation. To cite multiple items, use multiple pairs of brackets, like [T0B0] [T0B1].
            - Outside of citations, do not refer to item IDs.
            - Outside of citations, avoid quoting or paraphrasing the transcript.
            """
        )

        return f"{context_description}\n\n{citation_instructions}"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the context for database storage.

        Returns dictionary with explicit alias mappings and formatted object data.
        Formatted objects store full data inline, regular objects only store IDs
        for later database fetching.

        Returns:
            Dictionary suitable for JSONB storage
        """
        # Serialize alias dicts directly (JSON requires string keys)
        transcript_aliases_serialized = {
            str(idx): transcript.id for idx, transcript in self.transcript_aliases.items()
        }
        agent_run_aliases_serialized = {
            str(idx): agent_run.id for idx, agent_run in self.agent_run_aliases.items()
        }

        # Build formatted_data dict for all formatted objects
        formatted_data: dict[str, Any] = {}

        # Add formatted agent runs
        serialized_transcript_ids: set[str] = set()
        for agent_run in self.agent_run_aliases.values():
            if isinstance(agent_run, FormattedAgentRun):
                formatted_data[agent_run.id] = agent_run.model_dump(mode="json")
                serialized_transcript_ids.update(t.id for t in agent_run.transcripts)

        # Add formatted transcripts that aren't already included in output
        for transcript in self.transcript_aliases.values():
            if transcript.id in serialized_transcript_ids:
                continue
            if isinstance(transcript, FormattedTranscript):
                formatted_data[transcript.id] = transcript.model_dump(mode="json")

        return {
            "version": "1",
            "root_items": self.root_items,
            "transcript_aliases": transcript_aliases_serialized,
            "agent_run_aliases": agent_run_aliases_serialized,
            "formatted_data": formatted_data,
            "agent_run_collection_ids": self.agent_run_collection_ids,
            "transcript_to_agent_run": self.transcript_to_agent_run,
        }

    def resolve_item_alias(self, item_alias: str) -> ResolvedCitationItemUnion:
        # 1) T0B0M.key
        m = _MESSAGE_METADATA_RE.match(item_alias)
        if m:
            transcript_idx = int(m.group(1))
            block_idx = int(m.group(2))
            metadata_key = m.group(3)

            # Disallow nested keys like status.code
            if "." in metadata_key:
                raise ValueError(f"Nested keys are not allowed: {item_alias}")

            transcript = self.transcript_aliases[transcript_idx]
            agent_run_id = self.transcript_to_agent_run.get(transcript.id, "")
            collection_id = self.agent_run_collection_ids.get(agent_run_id, "")

            return TranscriptBlockMetadataItem(
                agent_run_id=agent_run_id,
                collection_id=collection_id,
                transcript_id=transcript.id,
                block_idx=block_idx,
                metadata_key=metadata_key,
            )

        # 2) T0M.key
        m = _TRANSCRIPT_METADATA_RE.match(item_alias)
        if m:
            transcript_idx = int(m.group(1))
            metadata_key = m.group(2)
            if "." in metadata_key:
                raise ValueError(f"Nested keys are not allowed: {item_alias}")

            transcript = self.transcript_aliases[transcript_idx]
            agent_run_id = self.transcript_to_agent_run.get(transcript.id, "")
            collection_id = self.agent_run_collection_ids.get(agent_run_id, "")

            return TranscriptMetadataItem(
                agent_run_id=agent_run_id,
                collection_id=collection_id,
                transcript_id=transcript.id,
                metadata_key=metadata_key,
            )

        # 3) R0M.key
        m = _AGENT_RUN_METADATA_RE.match(item_alias)
        if m:
            agent_run_idx = int(m.group(1))
            metadata_key = m.group(2)
            if "." in metadata_key:
                raise ValueError(f"Nested keys are not allowed: {item_alias}")
            agent_run = self.agent_run_aliases[agent_run_idx]
            collection_id = self.agent_run_collection_ids.get(agent_run.id, "")
            return AgentRunMetadataItem(
                agent_run_id=agent_run.id,
                collection_id=collection_id,
                metadata_key=metadata_key,
            )

        # 4) T0B0
        m = _SINGLE_RE.match(item_alias)
        if m:
            transcript_idx = int(m.group(1))
            block_idx = int(m.group(2))

            transcript = self.transcript_aliases[transcript_idx]
            agent_run_id = self.transcript_to_agent_run.get(transcript.id, "")
            collection_id = self.agent_run_collection_ids.get(agent_run_id, "")

            return TranscriptBlockContentItem(
                agent_run_id=agent_run_id,
                collection_id=collection_id,
                transcript_id=transcript.id,
                block_idx=block_idx,
            )

        raise ValueError(f"Unknown item alias: {item_alias}")


def _build_whitespace_flexible_regex(pattern: str) -> re.Pattern[str]:
    """Build regex that is flexible with whitespace matching."""
    out = ""
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch.isspace():
            while i < len(pattern) and pattern[i].isspace():
                i += 1
            out += r"\s+"
            continue
        out += re.escape(ch)
        i += 1
    return re.compile(out, re.DOTALL)


def _find_pattern_in_text(text: str, pattern: str | None) -> list[tuple[int, int]]:
    """Find all matches of a pattern in text.

    Returns list of (start_index, end_index) tuples for matches.
    """
    if not pattern:
        return []

    try:
        regex = _build_whitespace_flexible_regex(pattern)
        matches: list[tuple[int, int]] = []

        for match in regex.finditer(text):
            if match.group().strip():
                matches.append((match.start(), match.end()))

        return matches
    except re.error:
        return []


def _get_text_for_citation_target(target: CitationTarget, context: LLMContext) -> str | None:
    """Get the text content for a citation target."""
    item = target.item

    if isinstance(item, AgentRunMetadataItem):
        for agent_run in context.agent_run_aliases.values():
            if agent_run.id == item.agent_run_id:
                metadata_value = agent_run.metadata.get(item.metadata_key)
                if metadata_value is not None:
                    return json.dumps(metadata_value)
        return None

    if isinstance(item, TranscriptMetadataItem):
        for transcript in context.transcript_aliases.values():
            if transcript.id == item.transcript_id:
                metadata_value = transcript.metadata.get(item.metadata_key)
                if metadata_value is not None:
                    return json.dumps(metadata_value)
        return None

    if isinstance(item, TranscriptBlockMetadataItem):
        for transcript in context.transcript_aliases.values():
            if transcript.id == item.transcript_id:
                if 0 <= item.block_idx < len(transcript.messages):
                    message = transcript.messages[item.block_idx]
                    metadata_value = message.metadata.get(item.metadata_key)
                    if metadata_value is not None:
                        return json.dumps(metadata_value)
        return None

    # Must be TranscriptBlockContentItem at this point
    for t_idx, transcript in context.transcript_aliases.items():
        if transcript.id == item.transcript_id:
            if 0 <= item.block_idx < len(transcript.messages):
                message = transcript.messages[item.block_idx]
                return format_chat_message(message, f"T{t_idx}B{item.block_idx}")

    return None


def resolve_citations_with_context(
    text: str, context: LLMContext, validate_text_ranges: bool = True
) -> tuple[str, list[InlineCitation]]:
    """Parse citations and resolve agent run IDs using LLMContext.

    This function extends parse_citations to map local transcript IDs (T0, T1, etc.)
    back to their originating agent run IDs using the LLMContext.

    Args:
        text: The text to parse citations from
        context: LLMContext that maps transcript IDs to agent run IDs
        validate_text_ranges: If True, validate citation text ranges and set to None if invalid

    Returns:
        A tuple of (cleaned_text, citations) where citations include resolved agent_run_idx
    """
    cleaned_text, citations = parse_citations(text)
    resolved_citations: list[InlineCitation] = []

    for citation in citations:
        try:
            resolved_item = context.resolve_item_alias(citation.item_alias)
            text_range = citation.text_range

            target = CitationTarget(item=resolved_item, text_range=text_range)
            # Validate text range if requested and present
            if validate_text_ranges and text_range is not None:
                target_text = _get_text_for_citation_target(target, context)

                if target_text is not None:
                    matches = _find_pattern_in_text(target_text, text_range.start_pattern)
                    if len(matches) == 0:
                        target.text_range = None
                else:
                    target.text_range = None

            resolved_citations.append(
                InlineCitation(
                    start_idx=citation.start_idx,
                    end_idx=citation.end_idx,
                    target=target,
                )
            )
        except (KeyError, ValueError):
            # Unable to resolve citation target
            continue

    return cleaned_text, resolved_citations
