from __future__ import annotations

import json
import re
import sys
import textwrap
from enum import Enum, auto
from typing import Any, Literal

from pydantic import BaseModel, Field

from docent.data_models.agent_run import AgentRun, AgentRunTree, AgentRunView, SelectionSpec
from docent.data_models.citation import (
    AgentRunMetadataItem,
    AnalysisResultItem,
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


class _PromptSegmentType(Enum):
    BLOCK = auto()
    TEXT = auto()
    INLINE = auto()


def _prompt_segment_separator(prev: _PromptSegmentType, next: _PromptSegmentType) -> str:
    """What whitespace should exist between these segment types?"""
    if {prev, next} == {_PromptSegmentType.TEXT, _PromptSegmentType.INLINE}:
        return " "
    return "\n\n"


def _ensure_prompt_segment_separator(trailing: str, leading: str, target: str) -> str:
    """Return minimal string to insert so the gap contains target whitespace."""
    if target == "\n\n":
        trailing_newlines = len(trailing) - len(trailing.rstrip("\n"))
        leading_newlines = len(leading) - len(leading.lstrip("\n"))
        existing = trailing_newlines + leading_newlines
        return "\n" * max(0, 2 - existing)
    if target == " ":
        has_whitespace = (trailing and trailing[-1].isspace()) or (leading and leading[0].isspace())
        return "" if has_whitespace else " "
    return ""


def _ref_key(ref: "AgentRunRef | TranscriptRef | ResultRef") -> tuple[str, ...]:
    """Generate a unique key for a context item ref for deduplication."""
    if ref.type == "agent_run":
        return ("agent_run", ref.id, ref.collection_id)
    elif ref.type == "transcript":
        assert isinstance(ref, TranscriptRef)
        return ("transcript", ref.id, ref.collection_id)
    elif ref.type == "result":
        assert isinstance(ref, ResultRef)
        return ("result", ref.id, ref.result_set_id, ref.collection_id)
    raise ValueError(f"Unknown ref type: {type(ref)}")


class AgentRunRef(BaseModel):
    type: Literal["agent_run"] = "agent_run"
    id: str
    collection_id: str
    selection_spec: SelectionSpec | None = None


class TranscriptRef(BaseModel):
    type: Literal["transcript"] = "transcript"
    id: str
    agent_run_id: str
    collection_id: str


class ResultRef(BaseModel):
    type: Literal["result"] = "result"
    id: str
    result_set_id: str
    collection_id: str


ContextItemRef = AgentRunRef | TranscriptRef | ResultRef

_SINGLE_RE = re.compile(r"T(\d+)B(\d+)")
_AGENT_RUN_METADATA_RE = re.compile(r"^R(\d+)M\.([^:]+)$")  # [R0M.key]
_TRANSCRIPT_METADATA_RE = re.compile(r"^T(\d+)M\.([^:]+)$")  # [T0M.key]
_MESSAGE_METADATA_RE = re.compile(r"^T(\d+)B(\d+)M\.([^:]+)$")  # [T0B1M.key]
_ANALYSIS_RESULT_RE = re.compile(r"^A(\d+)$")  # [A0], [A1], etc.
_RANGE_CONTENT_RE = re.compile(r":\s*" + re.escape(RANGE_BEGIN) + r".*?" + re.escape(RANGE_END))


class LLMContextSpec(BaseModel):
    version: Literal["3"] = "3"
    root_items: list[str] = Field(default_factory=list)
    items: dict[str, ContextItemRef] = Field(default_factory=dict)
    inline_data: dict[str, Any] = Field(default_factory=dict)
    visibility: dict[str, bool] = Field(default_factory=dict)

    def _next_alias(self, prefix: Literal["R", "T", "A"]) -> str:
        used: set[int] = set()
        for alias in self.items.keys():
            if not alias.startswith(prefix):
                continue
            suffix = alias[1:]
            if suffix.isdigit():
                used.add(int(suffix))

        idx = 0
        while idx in used:
            idx += 1
        return f"{prefix}{idx}"

    def set_visibility(self, alias: str, visible: bool) -> None:
        if alias not in self.items:
            raise ValueError(f"Unknown alias: {alias}")
        if visible:
            self.visibility.pop(alias, None)
        else:
            self.visibility[alias] = False

    def remove_from_root(self, alias: str) -> None:
        if alias not in self.root_items:
            raise ValueError(f"Alias not in root_items: {alias}")
        self.root_items = [a for a in self.root_items if a != alias]
        self.visibility.pop(alias, None)

    def add_agent_run(
        self,
        *,
        id: str,
        collection_id: str,
        selection_spec: SelectionSpec | None = None,
    ) -> str:
        for alias, ref in self.items.items():
            if isinstance(ref, AgentRunRef) and ref.id == id:
                if alias not in self.root_items:
                    self.root_items.append(alias)
                if collection_id and ref.collection_id != collection_id:
                    ref.collection_id = collection_id
                if selection_spec is not None:
                    ref.selection_spec = selection_spec
                return alias

        alias = self._next_alias("R")
        self.items[alias] = AgentRunRef(
            id=id,
            collection_id=collection_id,
            selection_spec=selection_spec,
        )
        self.root_items.append(alias)
        return alias

    def add_transcript(
        self,
        *,
        id: str,
        agent_run_id: str,
        collection_id: str,
        is_root: bool = False,
    ) -> str:
        for alias, ref in self.items.items():
            if isinstance(ref, TranscriptRef) and ref.id == id:
                if is_root and alias not in self.root_items:
                    self.root_items.append(alias)
                if agent_run_id and ref.agent_run_id != agent_run_id:
                    ref.agent_run_id = agent_run_id
                if collection_id and ref.collection_id != collection_id:
                    ref.collection_id = collection_id
                return alias

        alias = self._next_alias("T")
        self.items[alias] = TranscriptRef(
            id=id,
            agent_run_id=agent_run_id,
            collection_id=collection_id,
        )
        if is_root:
            self.root_items.append(alias)
        return alias

    def add_result(
        self,
        *,
        id: str,
        result_set_id: str,
        collection_id: str,
    ) -> str:
        for alias, ref in self.items.items():
            if isinstance(ref, ResultRef) and ref.id == id:
                if alias not in self.root_items:
                    self.root_items.append(alias)
                return alias

        alias = self._next_alias("A")
        self.items[alias] = ResultRef(
            id=id,
            result_set_id=result_set_id,
            collection_id=collection_id,
        )
        self.root_items.append(alias)
        return alias

    def add_agent_run_from_object(
        self,
        agent_run: AgentRun,
        collection_id: str,
        selection_spec: SelectionSpec | None = None,
    ) -> str:
        alias = self.add_agent_run(
            id=agent_run.id,
            collection_id=collection_id,
            selection_spec=selection_spec,
        )

        tree = AgentRunTree.from_agent_run(agent_run)
        t_ids_ordered = sorted(
            tree.transcript_id_to_idx.keys(),
            key=lambda t_id: tree.transcript_id_to_idx[t_id],
        )
        for t_id in t_ids_ordered:
            transcript = agent_run.transcript_dict[t_id]
            self.add_transcript(
                id=transcript.id,
                agent_run_id=agent_run.id,
                collection_id=collection_id,
                is_root=False,
            )
        return alias

    def set_selection_spec(self, alias: str, spec: SelectionSpec | None) -> None:
        ref = self.items.get(alias)
        if ref is None:
            raise ValueError(f"Unknown alias: {alias}")
        if not isinstance(ref, AgentRunRef):
            raise ValueError(f"Alias is not an agent run: {alias}")
        ref.selection_spec = spec

    def set_inline_data(self, item_id: str, data: dict[str, Any] | None) -> None:
        if data is None:
            self.inline_data.pop(item_id, None)
            return
        self.inline_data[item_id] = data

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def resolve_item_alias(self, item_alias: str) -> ResolvedCitationItemUnion:
        # 1) T0B0M.key
        m = _MESSAGE_METADATA_RE.match(item_alias)
        if m:
            transcript_idx = int(m.group(1))
            block_idx = int(m.group(2))
            metadata_key = m.group(3)
            if "." in metadata_key:
                raise ValueError(f"Nested keys are not allowed: {item_alias}")

            t_alias = f"T{transcript_idx}"
            ref = self.items.get(t_alias)
            if ref is None or not isinstance(ref, TranscriptRef):
                raise ValueError(f"Unknown transcript alias: {t_alias}")

            return TranscriptBlockMetadataItem(
                agent_run_id=ref.agent_run_id,
                collection_id=ref.collection_id,
                transcript_id=ref.id,
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

            t_alias = f"T{transcript_idx}"
            ref = self.items.get(t_alias)
            if ref is None or not isinstance(ref, TranscriptRef):
                raise ValueError(f"Unknown transcript alias: {t_alias}")

            return TranscriptMetadataItem(
                agent_run_id=ref.agent_run_id,
                collection_id=ref.collection_id,
                transcript_id=ref.id,
                metadata_key=metadata_key,
            )

        # 3) R0M.key
        m = _AGENT_RUN_METADATA_RE.match(item_alias)
        if m:
            agent_run_idx = int(m.group(1))
            metadata_key = m.group(2)
            if "." in metadata_key:
                raise ValueError(f"Nested keys are not allowed: {item_alias}")

            r_alias = f"R{agent_run_idx}"
            ref = self.items.get(r_alias)
            if ref is None or not isinstance(ref, AgentRunRef):
                raise ValueError(f"Unknown agent run alias: {r_alias}")

            return AgentRunMetadataItem(
                agent_run_id=ref.id,
                collection_id=ref.collection_id,
                metadata_key=metadata_key,
            )

        # 4) T0B0
        m = _SINGLE_RE.match(item_alias)
        if m:
            transcript_idx = int(m.group(1))
            block_idx = int(m.group(2))

            t_alias = f"T{transcript_idx}"
            ref = self.items.get(t_alias)
            if ref is None or not isinstance(ref, TranscriptRef):
                raise ValueError(f"Unknown transcript alias: {t_alias}")

            return TranscriptBlockContentItem(
                agent_run_id=ref.agent_run_id,
                collection_id=ref.collection_id,
                transcript_id=ref.id,
                block_idx=block_idx,
            )

        # 5) A0
        m = _ANALYSIS_RESULT_RE.match(item_alias)
        if m:
            ref = self.items.get(item_alias)
            if ref is None or not isinstance(ref, ResultRef):
                raise ValueError(f"Unknown analysis result alias: {item_alias}")
            return AnalysisResultItem(
                result_set_id=ref.result_set_id,
                result_id=ref.id,
                collection_id=ref.collection_id,
            )

        raise ValueError(f"Unknown item alias: {item_alias}")


StorageSegment = str | dict[str, str]


class PromptData(BaseModel):
    """Serialized prompt data with alias references and context spec."""

    segments: list[StorageSegment] = Field(default_factory=list)
    spec: LLMContextSpec = Field(default_factory=LLMContextSpec)

    def to_storage(self) -> tuple[dict[str, Any], list[StorageSegment]]:
        """Convert to storage format (spec_dict, segments).

        Returns:
            Tuple of (llm_context_spec dict, prompt_segments list)
            where segments are either strings or {"alias": "R0"} dicts.
        """
        return self.spec.model_dump(mode="json"), self.segments


def Prompt(items: list[ContextItemRef | str]) -> PromptData:
    """Build a PromptData from refs and strings.

    Example:
        run1 = AgentRunRef(id="abc", collection_id="col1")
        run2 = AgentRunRef(id="def", collection_id="col1")

        # Simple case - \\n\\n added automatically between segments
        prompt = Prompt([run1, "Summarize this run."])

        # Interspersed - no manual \\n\\n needed
        prompt = Prompt([
            "Here is a successful run:", run1,
            "Here is a failed run:", run2,
            "Compare them."
        ])

        # Reference same item multiple times (first=full, subsequent=inline alias)
        prompt = Prompt([
            "Consider this run:", run,
            "Notice that ", run, " exhibits interesting behavior."
        ])
    """
    spec = LLMContextSpec()
    segments: list[StorageSegment] = []
    ref_key_to_alias: dict[tuple[str, ...], str] = {}

    for item in items:
        if isinstance(item, str):
            # Discard whitespace-only prompt segments
            if item.isspace():
                continue
            segments.append(item)
        else:
            ref = item
            key = _ref_key(ref)
            if key in ref_key_to_alias:
                alias = ref_key_to_alias[key]
            else:
                if ref.type == "agent_run":
                    alias = spec.add_agent_run(
                        id=ref.id,
                        collection_id=ref.collection_id,
                        selection_spec=ref.selection_spec,  # type: ignore[union-attr]
                    )
                elif ref.type == "transcript":
                    alias = spec.add_transcript(
                        id=ref.id,
                        agent_run_id=ref.agent_run_id,  # type: ignore[union-attr]
                        collection_id=ref.collection_id,
                        is_root=True,
                    )
                else:  # ResultRef
                    alias = spec.add_result(
                        id=ref.id,
                        result_set_id=ref.result_set_id,  # type: ignore[union-attr]
                        collection_id=ref.collection_id,
                    )
                ref_key_to_alias[key] = alias
            segments.append({"alias": alias})

    return PromptData(segments=segments, spec=spec)


class AnalysisResult(BaseModel):
    """A result loaded into LLM context for stringification and citation."""

    id: str
    result_set_id: str
    collection_id: str
    output: dict[str, Any] | None

    def to_text(self, alias: str) -> str:
        """Stringify this result for LLM context."""
        output_str = json.dumps(self.output, indent=2) if self.output else "(no output)"
        return f"<|analysis result {alias}|>\n{output_str}\n</|analysis result {alias}|>"


class LLMContext:
    def __init__(
        self,
        items: list[LLMContextItem] | None = None,
        *,
        spec: LLMContextSpec | None = None,
    ):
        self.spec = spec or LLMContextSpec()
        self.agent_runs: dict[str, AgentRun] = {}
        self.transcripts: dict[str, Transcript] = {}
        self.results: dict[str, AnalysisResult] = {}

        if items is not None:
            for item in items:
                self.add(item)

    @classmethod
    def from_spec(
        cls,
        spec: LLMContextSpec,
        *,
        agent_runs: dict[str, AgentRun],
        transcripts: dict[str, Transcript],
        results: dict[str, AnalysisResult],
    ) -> "LLMContext":
        spec_copy = spec.model_copy(deep=True)
        kept_items: dict[str, ContextItemRef] = {}
        for alias, ref in spec_copy.items.items():
            if isinstance(ref, AgentRunRef):
                if ref.id in agent_runs:
                    kept_items[alias] = ref
            elif isinstance(ref, TranscriptRef):
                if ref.id in transcripts:
                    kept_items[alias] = ref
            elif ref.id in results:
                kept_items[alias] = ref
        spec_copy.items = kept_items
        spec_copy.root_items = [alias for alias in spec_copy.root_items if alias in kept_items]
        spec_copy.visibility = {
            alias: v for alias, v in spec_copy.visibility.items() if alias in spec_copy.root_items
        }

        context = cls(spec=spec_copy)
        context.agent_runs = dict(agent_runs)
        context.transcripts = dict(transcripts)
        context.results = dict(results)
        return context

    @property
    def root_items(self) -> list[str]:
        return self.spec.root_items

    @property
    def item_visibility(self) -> dict[str, bool]:
        return self.spec.visibility

    def build_agent_run_view(self, alias: str) -> AgentRunView:
        ref = self.spec.items.get(alias)
        if ref is None:
            raise ValueError(f"Unknown alias: {alias}")
        if not isinstance(ref, AgentRunRef):
            raise ValueError(f"Alias is not an agent run: {alias}")

        agent_run = self.agent_runs.get(ref.id)
        if agent_run is None:
            raise ValueError(f"Agent run {ref.id} not loaded")
        return AgentRunView(agent_run=agent_run, selection_spec=ref.selection_spec)

    def add(self, item: LLMContextItem, *, collection_id: str = "") -> str:
        if isinstance(item, AgentRun):
            agent_run = item
            alias = self.spec.add_agent_run_from_object(
                agent_run=agent_run,
                collection_id=collection_id,
                selection_spec=None,
            )
            self.agent_runs[agent_run.id] = agent_run

            if isinstance(agent_run, FormattedAgentRun):
                self.spec.set_inline_data(agent_run.id, agent_run.model_dump(mode="json"))

            for transcript in agent_run.transcripts:
                self.transcripts[transcript.id] = transcript

            return alias
        elif isinstance(item, Transcript):  # type: ignore
            transcript = item
            agent_run_id = ""
            for ref in self.spec.items.values():
                if isinstance(ref, TranscriptRef) and ref.id == transcript.id:
                    agent_run_id = ref.agent_run_id
                    if ref.collection_id:
                        collection_id = ref.collection_id
                    break
            alias = self.spec.add_transcript(
                id=transcript.id,
                agent_run_id=agent_run_id,
                collection_id=collection_id,
                is_root=True,
            )
            self.transcripts[transcript.id] = transcript
            if isinstance(transcript, FormattedTranscript):
                self.spec.set_inline_data(transcript.id, transcript.model_dump(mode="json"))
            return alias
        else:
            raise ValueError(f"Unknown item type: {type(item)}")

    def to_str(self, token_limit: int = sys.maxsize) -> str:
        sections: list[str] = []

        id_to_idx_map = {
            ref.id: int(alias[1:])
            for alias, ref in self.spec.items.items()
            if isinstance(ref, TranscriptRef) and alias.startswith("T") and alias[1:].isdigit()
        }

        for alias in self.spec.root_items:
            if self.spec.visibility.get(alias) is False:
                continue

            ref = self.spec.items.get(alias)
            if ref is None:
                raise ValueError(f"Unknown alias: {alias}")

            if isinstance(ref, TranscriptRef):
                transcript = self.transcripts.get(ref.id)
                if transcript is None:
                    raise ValueError(f"Transcript {ref.id} not loaded")
                sections.append(transcript.to_text(transcript_alias=alias))
                continue

            if isinstance(ref, ResultRef):
                result = self.results.get(ref.id)
                if result is None:
                    raise ValueError(f"Result {ref.id} not loaded")
                sections.append(result.to_text(alias))
                continue

            view = self.build_agent_run_view(alias)
            sections.append(view.to_text(agent_run_alias=alias, t_idx_map=id_to_idx_map))
            continue

        return "\n\n".join(sections)

    def render_segments(self, segments: list[str | dict[str, str]]) -> str:
        """Render a list of segments to a string.

        Segments can be:
        - Plain text strings (rendered as-is)
        - {"alias": "R0"} dicts (typed alias references - new format)
        - Legacy: bare alias strings that exist in spec.items

        Segment types:
        - BLOCK: first occurrence of an alias (renders full content)
        - TEXT: plain text
        - INLINE: subsequent occurrence of an alias (renders as [alias])

        Separation policy:
        - TEXT <-> INLINE: ensure at least one whitespace character
        - All other transitions: ensure a blank line (two newlines)
        """
        id_to_idx_map = {
            ref.id: int(alias[1:])
            for alias, ref in self.spec.items.items()
            if isinstance(ref, TranscriptRef) and alias.startswith("T") and alias[1:].isdigit()
        }

        rendered_aliases: set[str] = set()
        parts: list[str] = []
        prev_type: _PromptSegmentType | None = None

        for seg in segments:
            if isinstance(seg, dict) and "alias" in seg:
                alias = seg["alias"]
                if alias in rendered_aliases:
                    content = f"[{alias}]"
                    seg_type = _PromptSegmentType.INLINE
                else:
                    content = self._render_item(alias, id_to_idx_map)
                    rendered_aliases.add(alias)
                    seg_type = _PromptSegmentType.BLOCK
            else:
                content = str(seg)
                seg_type = _PromptSegmentType.TEXT

            if prev_type is not None:
                target = _prompt_segment_separator(prev_type, seg_type)
                trailing = parts[-1] if parts else ""
                parts.append(_ensure_prompt_segment_separator(trailing, content, target))

            parts.append(content)
            prev_type = seg_type

        return "".join(parts)

    def _render_item(self, alias: str, id_to_idx_map: dict[str, int]) -> str:
        """Render a single item by alias."""
        ref = self.spec.items.get(alias)
        if ref is None:
            raise ValueError(f"Unknown alias: {alias}")

        if isinstance(ref, TranscriptRef):
            transcript = self.transcripts.get(ref.id)
            if transcript is None:
                raise ValueError(f"Transcript {ref.id} not loaded")
            return transcript.to_text(transcript_alias=alias)

        if isinstance(ref, ResultRef):
            result = self.results.get(ref.id)
            if result is None:
                raise ValueError(f"Result {ref.id} not loaded")
            return result.to_text(alias)

        # Must be AgentRunRef at this point
        view = self.build_agent_run_view(alias)
        return view.to_text(agent_run_alias=alias, t_idx_map=id_to_idx_map)

    def get_system_message(self, interactive: bool = True, include_citations: bool = True) -> str:
        """Generate a system prompt with citation instructions for multi-object context.

        Args:
            interactive: Whether this is an interactive session
            include_citations: Whether to include citation instructions in the system message

        Returns:
            System message string with instructions on how to cite objects
        """

        if interactive:
            context_description = "You are a helpful assistant that specializes in analyzing transcripts of AI agent behavior."
        else:
            context_description = "You are a tasked with analyzing transcripts of AI agent behavior. You are not interacting with a user directly."

        if not include_citations:
            return context_description

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
            - Item IDs are ONLY to be used inside citation brackets. Do NOT use item IDs anywhere else.
            - Outside of citations, avoid quoting or paraphrasing the transcript.
            """
        )

        return f"{context_description}\n\n{citation_instructions}"

    def to_dict(self) -> dict[str, Any]:
        return self.spec.to_dict()

    def resolve_item_alias(self, item_alias: str) -> ResolvedCitationItemUnion:
        return self.spec.resolve_item_alias(item_alias)


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
        agent_run = context.agent_runs.get(item.agent_run_id)
        if agent_run is None:
            return None
        metadata_value = agent_run.metadata.get(item.metadata_key)
        return None if metadata_value is None else json.dumps(metadata_value)

    if isinstance(item, TranscriptMetadataItem):
        transcript = context.transcripts.get(item.transcript_id)
        if transcript is None:
            return None
        metadata_value = transcript.metadata.get(item.metadata_key)
        return None if metadata_value is None else json.dumps(metadata_value)

    if isinstance(item, TranscriptBlockMetadataItem):
        transcript = context.transcripts.get(item.transcript_id)
        if transcript is None:
            return None
        if not (0 <= item.block_idx < len(transcript.messages)):
            return None
        message = transcript.messages[item.block_idx]
        metadata_value = message.metadata.get(item.metadata_key) if message.metadata else None
        return None if metadata_value is None else json.dumps(metadata_value)

    if isinstance(item, AnalysisResultItem):
        for alias, result in context.results.items():
            if result.id == item.result_id and result.result_set_id == item.result_set_id:
                return None if result.output is None else json.dumps(result.output)
        return None

    # At this point, item must be TranscriptBlockContentItem
    transcript = context.transcripts.get(item.transcript_id)
    if transcript is None:
        return None
    if not (0 <= item.block_idx < len(transcript.messages)):
        return None

    transcript_alias: str | None = None
    for alias, ref in context.spec.items.items():
        if isinstance(ref, TranscriptRef) and ref.id == item.transcript_id:
            transcript_alias = alias
            break
    if transcript_alias is None:
        return None

    message = transcript.messages[item.block_idx]
    return format_chat_message(message, f"{transcript_alias}B{item.block_idx}")


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
