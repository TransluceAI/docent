import textwrap
from datetime import datetime
from typing import Any, Iterable
from uuid import uuid4

from pydantic import BaseModel, Field

from docent.data_models.chat import AssistantMessage, ChatMessage, ContentReasoning
from docent.data_models.citation import (
    RANGE_BEGIN,
    RANGE_END,
    AgentRunMetadataItem,
    CitationTargetTextRange,
    Comment,
    TranscriptBlockContentItem,
    TranscriptMetadataItem,
)
from docent.data_models.metadata_util import dump_metadata


def render_metadata_comments(comments: list[Comment]) -> str:
    """Render metadata comments (agent run, transcript, or block metadata).

    For metadata comments, we render the key on which the comment was written
    and the user's content.

    TODO(mengk): known limitation: does not highlight text_range selections, if available.
        I'm not sure if it's supported in the UI, but just pointing this out for the backend.

    Args:
        comments: List of Comment objects targeting metadata.

    Returns:
        Formatted string with all comments.
    """
    if not comments:
        return ""

    lines: list[str] = []
    for comment in comments:
        # Iterate through citations to find the right target
        metadata_key = "unknown"
        for citation in comment.citations:
            item = citation.target.item
            if isinstance(item, TranscriptMetadataItem):
                metadata_key = item.metadata_key
                break
            elif isinstance(item, AgentRunMetadataItem):
                metadata_key = item.metadata_key
                break
        lines.append(f'<comment key="{metadata_key}">{comment.content}</comment>')

    return "\n".join(lines)


def render_block_content_comments(
    comments: list[Comment],
    content: str,
    comment_index_offset: int = 0,
) -> tuple[str, str]:
    """Render block content comments with text range highlighting.

    For block content comments with text_range, we surround the range with
    <COMMENT_X_SELECTION></COMMENT_X_SELECTION> tags and render the comment
    content below with a reference to the selection.

    Args:
        comments: List of Comment objects targeting block content.
        content: The block content text to annotate.
        comment_index_offset: Starting index for comment numbering (local to message).

    Returns:
        Tuple of (annotated_content, comments_text) where annotated_content has
        selection tags inserted and comments_text contains the rendered comments.
    """
    if not comments:
        return content, ""

    # Build a list of (position, tag_text) for all tag insertions.
    # By treating start and end tags as independent insertions sorted by position
    # descending, we correctly handle overlapping/nested ranges. Each insertion
    # only affects positions after it, so processing from the end backward
    # preserves all indices.
    insertions: list[tuple[int, str]] = []
    comments_with_text_range: set[str] = set()
    for i, comment in enumerate(comments):
        # Iterate through citations to find the right target
        text_range: CitationTargetTextRange | None = None
        for citation in comment.citations:
            item = citation.target.item
            if isinstance(item, TranscriptBlockContentItem):
                text_range = citation.target.text_range
                break

        # If the text range exists, add the start and end tags
        if (
            text_range
            and text_range.target_start_idx is not None
            and text_range.target_end_idx is not None
        ):
            start_idx = text_range.target_start_idx
            end_idx = text_range.target_end_idx
            if 0 <= start_idx < len(content) and start_idx < end_idx <= len(content):
                # End tag goes at end_idx, start tag goes at start_idx
                comment_idx = comment_index_offset + i
                insertions.append((end_idx, f"</COMMENT_{comment_idx}_SELECTION>"))
                insertions.append((start_idx, f"<COMMENT_{comment_idx}_SELECTION>"))

                # Keep track of comments with text ranges
                comments_with_text_range.add(comment.id)

    # Sort by position descending. For ties (e.g., end of one range = start of another),
    # end tags (closing) should come before start tags (opening) at the same position
    # to produce valid nesting, but since our tags don't need to be valid XML, order
    # at ties doesn't matter for correctness.
    insertions.sort(key=lambda x: x[0], reverse=True)

    # Apply insertions from the end backward to preserve indices
    annotated_content = content
    for pos, tag in insertions:
        annotated_content = annotated_content[:pos] + tag + annotated_content[pos:]

    # Build comment text
    comment_lines: list[str] = []
    for i, comment in enumerate(comments):
        if comment.id in comments_with_text_range:
            comment_idx = comment_index_offset + i
            comment_lines.append(
                f'<comment selection="COMMENT_{comment_idx}_SELECTION">{comment.content}</comment>'
            )
        else:
            comment_lines.append(f"<comment>{comment.content}</comment>")

    return annotated_content, "\n".join(comment_lines)


# Template for formatting individual transcript blocks
TRANSCRIPT_BLOCK_TEMPLATE = """
<|{index_label}; role: {role}|>
{content}
</|{index_label}; role: {role}|>
""".strip()

# Instructions for citing single transcript blocks
TEXT_RANGE_CITE_INSTRUCTION = f"""Anytime you quote the transcript, or refer to something that happened in the transcript, or make any claim about the transcript, add an inline citation. Each transcript and each block has a unique index. Cite the relevant indices in brackets. For example, to cite the entirety of transcript 0, block 1, write [T0B1].

A citation may include a specific range of text within a block. Use {RANGE_BEGIN} and {RANGE_END} to mark the specific range of text. Add it after the block ID separated by a colon. For example, to cite the part of transcript 0, block 1, where the agent says "I understand the task", write [T0B1:{RANGE_BEGIN}I understand the task{RANGE_END}]. Citations must follow this exact format. The markers {RANGE_BEGIN} and {RANGE_END} must be used ONLY inside the brackets of a citation.

- You may cite a top-level key in the agent run metadata like this: [M.task_description].
- You may cite a top-level key in transcript metadata. For example, for transcript 0: [T0M.start_time].
- You may cite a top-level key in message metadata for a block. For example, for transcript 0, block 1: [T0B1M.status].
- You may not cite nested keys. For example, [T0B1M.status.code] is invalid.
- Within a top-level metadata key you may cite a range of text that appears in the value. For example, [T0B1M.status:{RANGE_BEGIN}"running":false{RANGE_END}].

Important notes:
- You must include the full content of the text range {RANGE_BEGIN} and {RANGE_END}, EXACTLY as it appears in the transcript, word-for-word, including any markers or punctuation that appear in the middle of the text.
- Citations must be as specific as possible. This means you should usually cite a specific text range within a block.
- A citation is not a quote. For brevity, text ranges will not be rendered inline. The user will have to click on the citation to see the full text range.
- Citations are self-contained. Do NOT label them as citation or evidence. Just insert the citation by itself at the appropriate place in the text.
- Citations must come immediately after the part of a claim that they support. This may be in the middle of a sentence.
- Each pair of brackets must contain only one citation. To cite multiple blocks, use multiple pairs of brackets, like [T0B0] [T0B1].
- Outside of citations, do not refer to transcript numbers or block numbers.
- Outside of citations, avoid quoting or paraphrasing the transcript.
"""

BLOCK_CITE_INSTRUCTION = """Each transcript and each block has a unique index. Cite the relevant indices in brackets when relevant, like [T<idx>B<idx>]. Use multiple tags to cite multiple blocks, like [T<idx1>B<idx1>][T<idx2>B<idx2>]. Remember to cite specific blocks and NOT action units."""


def format_chat_message(
    message: ChatMessage,
    index_label: str,
    block_metadata_comments: list[Comment] | None = None,
    block_content_comments: list[Comment] | None = None,
    indent: int = 0,
) -> str:
    cur_content = ""

    # Add reasoning at beginning if applicable
    if isinstance(message, AssistantMessage) and message.content:
        for content in message.content:
            if isinstance(content, ContentReasoning):
                cur_content = f"<reasoning>\n{content.reasoning}\n</reasoning>\n"

    # Main content text
    cur_content += message.text

    # Update content in case there's a view
    if isinstance(message, AssistantMessage) and message.tool_calls:
        for tool_call in message.tool_calls:
            if tool_call.view:
                cur_content += f"\n<tool call>\n{tool_call.view.content}\n</tool call>"
            else:
                args = ", ".join([f"{k}={v}" for k, v in tool_call.arguments.items()])
                cur_content += f"\n<tool call>\n{tool_call.function}({args})\n</tool call>"

    # Apply block content comments (with text range highlighting)
    block_content_comments_text = ""
    if block_content_comments:
        cur_content, block_content_comments_text = render_block_content_comments(
            block_content_comments, cur_content
        )

    # Add block content comments right below the content (before metadata)
    if block_content_comments_text:
        if indent > 0:
            block_content_comments_text = textwrap.indent(block_content_comments_text, " " * indent)
        cur_content += f"\n<|block content comments|>\n{block_content_comments_text}\n</|block content comments|>"

    # Add message metadata
    if message.metadata:
        metadata_text = dump_metadata(message.metadata)
        if metadata_text is not None:
            cur_content += f"\n<|message metadata|>\n{metadata_text}\n</|message metadata|>"

    # Add block metadata comments after the metadata
    if block_metadata_comments:
        metadata_comments_text = render_metadata_comments(block_metadata_comments)
        if metadata_comments_text:
            if indent > 0:
                metadata_comments_text = textwrap.indent(metadata_comments_text, " " * indent)
            cur_content += f"\n<|block metadata comments|>\n{metadata_comments_text}\n</|block metadata comments|>"

    return TRANSCRIPT_BLOCK_TEMPLATE.format(
        index_label=index_label, role=message.role, content=cur_content
    )


class TranscriptGroup(BaseModel):
    """Represents a group of transcripts that are logically related.

    A transcript group can contain multiple transcripts and can have a hierarchical
    structure with parent groups. This is useful for organizing transcripts into
    logical units like experiments, tasks, or sessions.

    Attributes:
        id: Unique identifier for the transcript group, auto-generated by default.
        name: Optional human-readable name for the transcript group.
        description: Optional description of the transcript group.
        collection_id: ID of the collection this transcript group belongs to.
        agent_run_id: ID of the agent run this transcript group belongs to.
        parent_transcript_group_id: Optional ID of the parent transcript group.
        metadata: Additional structured metadata about the transcript group.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    description: str | None = None
    agent_run_id: str
    parent_transcript_group_id: str | None = None
    created_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_text(self, children_text: str, indent: int = 0, render_metadata: bool = True) -> str:
        """Render this transcript group with its children and metadata.

        Metadata appears below the rendered children content.

        Args:
            children_text: Pre-rendered text of this group's children (groups/transcripts).
            indent: Number of spaces to indent the rendered output.
            render_metadata: Whether to include metadata in the output.

        Returns:
            str: XML-like wrapped text including the group's metadata.
        """
        # Prepare YAML metadata
        if render_metadata:
            metadata_text = dump_metadata(self.metadata)
            if metadata_text is not None:
                if indent > 0:
                    metadata_text = textwrap.indent(metadata_text, " " * indent)
                inner = f"{children_text}\n<|{self.name} metadata|>\n{metadata_text}\n</|{self.name} metadata|>"
            else:
                inner = children_text
        else:
            inner = children_text

        # Compose final text: content first, then metadata, all inside the group wrapper
        if indent > 0:
            inner = textwrap.indent(inner, " " * indent)
        return f"<|{self.name}|>\n{inner}\n</|{self.name}|>"


class Transcript(BaseModel):
    """Represents a transcript of messages in a conversation with an AI agent.

    A transcript contains a sequence of messages exchanged between different roles
    (system, user, assistant, tool) and provides methods to organize these messages
    into logical units of action.

    Attributes:
        id: Unique identifier for the transcript, auto-generated by default.
        name: Optional human-readable name for the transcript.
        description: Optional description of the transcript.
        transcript_group_id: Optional ID of the transcript group this transcript belongs to.
        messages: List of chat messages in the transcript.
        metadata: Additional structured metadata about the transcript.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str | None = None
    description: str | None = None
    transcript_group_id: str | None = None
    created_at: datetime | None = None

    messages: list[ChatMessage]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def _enumerate_messages(self) -> Iterable[tuple[int, ChatMessage]]:
        """Yield (index, message) tuples for rendering.

        Override in subclasses to customize index assignment.
        """
        return enumerate(self.messages)

    def to_text(
        self,
        transcript_alias: int | str = 0,
        indent: int = 0,
        render_metadata: bool = True,
        transcript_metadata_comments: list[Comment] | None = None,
        block_metadata_comments: dict[int, list[Comment]] | None = None,
        block_content_comments: dict[int, list[Comment]] | None = None,
    ) -> str:
        """Render this transcript as formatted text with optional comments.

        Args:
            transcript_alias: Identifier for the transcript (e.g., 0 becomes "T0").
            indent: Number of spaces to indent nested content.
            render_metadata: Whether to include transcript metadata in the output.
            transcript_metadata_comments: Comments on this transcript's metadata.
                Rendered after the transcript metadata block.
            block_metadata_comments: Mapping from block index to comments on that
                block's metadata. Keyed by block index because comments need to be
                rendered inline with each block at the correct position.
            block_content_comments: Mapping from block index to comments on that
                block's content. Keyed by block index because comments need to be
                rendered inline with each block, and may include text range
                selections that highlight specific portions of the block content.

        Returns:
            Formatted text representation of the transcript.
        """
        if isinstance(transcript_alias, int):
            transcript_alias = f"T{transcript_alias}"

        # Format individual message blocks
        blocks: list[str] = []
        for msg_idx, message in self._enumerate_messages():
            block_label = f"{transcript_alias}B{msg_idx}"
            # Get block-level comments for this message index
            msg_metadata_comments = (
                block_metadata_comments.get(msg_idx) if block_metadata_comments else None
            )
            msg_content_comments = (
                block_content_comments.get(msg_idx) if block_content_comments else None
            )
            block_text = format_chat_message(
                message,
                block_label,
                block_metadata_comments=msg_metadata_comments,
                block_content_comments=msg_content_comments,
                indent=indent,
            )
            blocks.append(block_text)
        blocks_str = "\n".join(blocks)
        if indent > 0:
            blocks_str = textwrap.indent(blocks_str, " " * indent)

        content_str = f"<|{transcript_alias} blocks|>\n{blocks_str}\n</|{transcript_alias} blocks|>"

        # Gather metadata and add to content
        if render_metadata:
            metadata_text = dump_metadata(self.metadata)
            if metadata_text is not None:
                if indent > 0:
                    metadata_text = textwrap.indent(metadata_text, " " * indent)
                metadata_label = f"{transcript_alias}M"
                content_str += f"\n<|transcript metadata {metadata_label}|>\n{metadata_text}\n</|transcript metadata {metadata_label}|>"

            # Add transcript metadata comments after the metadata
            if transcript_metadata_comments:
                metadata_comments_text = render_metadata_comments(transcript_metadata_comments)
                if metadata_comments_text:
                    if indent > 0:
                        metadata_comments_text = textwrap.indent(
                            metadata_comments_text, " " * indent
                        )
                    content_str += f"\n<|transcript metadata comments|>\n{metadata_comments_text}\n</|transcript metadata comments|>"

        # Format content and return
        if indent > 0:
            content_str = textwrap.indent(content_str, " " * indent)
        return f"<|transcript {transcript_alias}|>\n{content_str}\n</|transcript {transcript_alias}|>\n"
