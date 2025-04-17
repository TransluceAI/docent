import json
import re
from typing import Any, TypedDict

from IPython.display import HTML, display  # type: ignore
from llm_util.types import ChatMessage, ChatMessageAssistant, ChatMessageContentReasoning
from pydantic import BaseModel, Field, PrivateAttr

TRANSCRIPT_BLOCK_TEMPLATE = """
<{index_label} | role: {role}>
{content}
</{index_label}>
""".strip()
SINGLE_BLOCK_CITE_INSTRUCTION = "Each transcript block has a unique index; cite the relevant block index in brackets when relevant, like [B<idx>]. Use multiple tags to cite multiple blocks, like [B<idx1>][B<idx2>]. Use dashes to cite ranges, like [B<idx1>-B<idx2>], but cite ranges sparingly; do your best to be specific."
MULTI_BLOCK_CITE_INSTRUCTION = "Each transcript block has a unique index; cite the relevant block index in brackets when relevant, like [T<idx>B<idx>]. Use multiple tags to cite multiple blocks, like [T<idx1>B<idx1>][T<idx2>B<idx2>]. Use dashes to cite ranges, like [T<idx1>B<idx1>-T<idx2>B<idx2>], but cite ranges sparingly; do your best to be specific."
DEFAULT_TO_STR_METADATA_FIELDS = ["scores", "additional_metadata"]


class TranscriptMetadata(BaseModel):
    task_id: str = Field(
        description="The ID of the 'benchmark' or 'set of evals' that the transcript belongs to"
    )

    # Identification of this particular run
    sample_id: str | int = Field(
        description="The specific task inside of the `task_id` benchmark that the transcript was run on"
    )
    epoch_id: int = Field(
        description="Each `sample_id` should be run multiple times due to stochasticity; `epoch_id` is the integer index of a specific run."
    )

    # Experiment
    experiment_id: str = Field(
        description="Each 'experiment' is a run of a subset of samples under some configuration. This is the ID of the experiment that the transcript belongs to."
    )
    intervention_description: str | None = Field(
        description="Experiments may involve interventions on the chat message history (e.g., to change what the model did or provide hints). This is a natural language description of the intervention that was applied, if any."
    )
    intervention_index: int | None = Field(
        description="The integer index in the list of chat messages that the intervention, if any, was applied to"
    )
    intervention_timestamp: str | None = Field(
        description="The timestamp of the intervention, if any"
    )

    # Parameters for the run
    model: str = Field(description="The model that was used to generate the transcript")
    task_args: dict[str, Any] = Field(
        description="[Inspect-specific] Inspect TaskArgs used to generate the transcript"
    )
    is_loading_messages: bool = Field(
        description="Whether the transcript is un-finalized and still loading messages"
    )

    # Outcome
    scores: dict[str, int | float | bool] = Field(
        description="A dict of score_keys -> score_values for the transcript; supports multiple metrics"
    )
    default_score_key: str | None = Field(
        description="The default score key for the transcript; one top-line metric"
    )
    scoring_metadata: dict[str, Any] | None = Field(
        description="Additional metadata about the scoring process"
    )

    # Inspect metadata
    additional_metadata: dict[str, Any] | None = Field(
        description="Additional metadata about the transcript"
    )

    def get_default_score(self) -> int | float | bool | None:
        if self.default_score_key is None:
            return None
        return self.scores.get(self.default_score_key)


def format_chat_message(
    transcript_idx: int | None, block_idx: int | None, message: ChatMessage
) -> str:
    if transcript_idx is not None and block_idx is not None:
        index_label = f"T{transcript_idx}B{block_idx}"
    elif transcript_idx is not None:
        index_label = f"T{transcript_idx}"
    elif block_idx is not None:
        index_label = f"B{block_idx}"
    else:
        index_label = ""

    cur_content = ""

    # Add reasoning at beginning if applicable
    if isinstance(message, ChatMessageAssistant) and message.content:
        for content in message.content:
            if isinstance(content, ChatMessageContentReasoning):
                cur_content = f"<reasoning>\n{content.reasoning}\n</reasoning>\n"

    # Main content text
    cur_content += message.text

    # Update content in case there's a view
    if isinstance(message, ChatMessageAssistant) and message.tool_calls:
        for tool_call in message.tool_calls:
            if tool_call.view:
                cur_content += f"\n<tool call>\n{tool_call.view.content}\n</tool call>"
            else:
                args = ", ".join([f"{k}={v}" for k, v in tool_call.arguments.items()])
                cur_content += f"\n<tool call>\n{tool_call.function}({args})\n</tool call>"

    return TRANSCRIPT_BLOCK_TEMPLATE.format(
        index_label=index_label, role=message.role, content=cur_content
    )


class Transcript(BaseModel):
    messages: list[ChatMessage]
    metadata: TranscriptMetadata

    # Private attributes
    _units_of_action: list[list[int]] | None = PrivateAttr(default=None)

    @property
    def sample_id(self) -> str | int:
        """Deprecated; use metadata.sample_id instead."""
        return self.metadata.sample_id

    @property
    def epoch_id(self) -> int:
        """Deprecated; use metadata.epoch_id instead."""
        return self.metadata.epoch_id

    @property
    def units_of_action(self) -> list[list[int]]:
        if self._units_of_action is None:
            self._units_of_action = self._compute_units_of_action()
        return self._units_of_action

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self._units_of_action = self._compute_units_of_action()

    def _compute_units_of_action(self) -> list[list[int]]:
        """
        Returns a list of "units of action" in the transcript.

        A unit of action is defined as:
        - A system prompt by itself
        - A group consisting of a user message, assistant response, and any associated tool outputs

        Returns:
            list[list[ChatMessage]]: A list of units of action, where each unit is a list of messages
        """
        if not self.messages:
            return []

        units: list[list[int]] = []
        current_unit: list[int] = []

        def _start_new_unit():
            nonlocal current_unit
            if current_unit:
                units.append(current_unit.copy())
            current_unit = []

        for i, message in enumerate(self.messages):
            role = message.role
            prev_message = self.messages[i - 1] if i > 0 else None

            # System messages are their own unit
            if role == "system":
                assert not current_unit, "System message should be the first message"
                units.append([i])

            # User message always starts a new unit UNLESS the previous message was a user message
            elif role == "user":
                if current_unit and prev_message and prev_message.role != "user":
                    _start_new_unit()
                current_unit.append(i)

            # Start a new unit if the previous message was not a user or assistant message
            elif role == "assistant":
                if (
                    current_unit
                    and prev_message
                    and prev_message.role != "user"
                    and prev_message.role != "assistant"
                ):
                    _start_new_unit()
                current_unit.append(i)

            # Tool messages are part of the current unit
            elif role == "tool":
                current_unit.append(i)

            else:
                raise ValueError(f"Unknown message role: {role}")

        # Add the last unit if it exists
        _start_new_unit()

        return units

    def get_first_block_in_action_unit(self, action_unit_idx: int) -> int | None:
        """
        Returns the first block index in a given action unit.

        Args:
            action_unit_idx: The index of the action unit

        Returns:
            The first block index in the action unit, or None if the action unit doesn't exist
        """
        if not self._units_of_action:
            self._units_of_action = self._compute_units_of_action()

        if 0 <= action_unit_idx < len(self._units_of_action):
            unit = self._units_of_action[action_unit_idx]
            return unit[0] if unit else None
        return None

    def get_action_unit_for_block(self, block_idx: int) -> int | None:
        if not self._units_of_action:
            self._units_of_action = self._compute_units_of_action()

        for unit_idx, unit in enumerate(self._units_of_action):
            if block_idx in unit:
                return unit_idx
        return None

    def set_messages(self, messages: list[ChatMessage]):
        self.messages = messages
        self._units_of_action = self._compute_units_of_action()

    def to_str(
        self,
        metadata_fields: list[str] | None = DEFAULT_TO_STR_METADATA_FIELDS,
        transcript_idx_label: int | None = None,
        highlight_action_unit: int | None = None,
        max_action_unit_idx: int | None = None,
    ):
        if highlight_action_unit is not None and not (
            0 <= highlight_action_unit < len(self._units_of_action or [])
        ):
            raise ValueError(f"Invalid action unit index: {highlight_action_unit}")
        if max_action_unit_idx is not None and max_action_unit_idx >= len(
            self._units_of_action or []
        ):
            raise ValueError(f"Invalid max action unit index: {max_action_unit_idx}")

        # Format blocks by units of action
        au_blocks: list[str] = []
        for unit_idx, unit in enumerate(self._units_of_action or []):
            if max_action_unit_idx is not None and unit_idx > max_action_unit_idx:
                break

            unit_blocks: list[str] = []
            for msg_idx in unit:
                unit_blocks.append(
                    format_chat_message(transcript_idx_label, msg_idx, self.messages[msg_idx])
                )

            unit_content = "\n".join(unit_blocks)

            # Add highlighting if requested
            if highlight_action_unit and unit_idx == highlight_action_unit:
                blocks_str_template = "<HIGHLIGHTED>\n{}\n</HIGHLIGHTED>"
            else:
                blocks_str_template = "{}"
            au_blocks.append(
                blocks_str_template.format(
                    f"<action unit {unit_idx}>\n{unit_content}\n</action unit {unit_idx}>"
                )
            )
        blocks_str = "\n".join(au_blocks)

        # Gather metadata
        metadata_fields_set = set(metadata_fields) if metadata_fields is not None else None
        metadata_obj = (
            {
                k: v
                for k, v in self.metadata.model_dump().items()
                if metadata_fields_set is None or k in metadata_fields_set
            }
            if self.metadata
            else {}
        )

        return f"""
AI agent transcript for analysis:
<transcript>
{blocks_str}
</transcript>

Additional metadata about the task (the agent can't access metadata; you may use it for analysis but do NOT cite it):
<metadata>
{json.dumps(metadata_obj)}
</metadata>
        """.strip()

    def display_html(self) -> None:
        """
        Display the transcript HTML in IPython.
        """
        display(HTML(self.to_html()))

    def to_html(self) -> str:
        """
        Renders the transcript as styled HTML with message boxes and proper formatting.
        """
        css = """<style>
    .transcript-container {
        font-family: 'Courier New', Courier, monospace;
        max-width: 1000px;
        color: #000000;
    }
    .message-container {
        margin: 12px 0;
        padding: 12px;
        border-radius: 8px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .assistant-message {
        background-color: #f1f7ff;
        border-left: 4px solid #0066cc;
        color: #000000;
    }
    .user-message {
        background-color: #f5f5f5;
        border-left: 4px solid #666666;
        color: #000000;
    }
    .system-message {
        background-color: #fff3e0;
        border-left: 4px solid #ff9800;
        color: #000000;
    }
    .message-header {
        font-size: 0.9em;
        color: #333333;  /* Darker header text */
        margin-bottom: 8px;
        display: flex;
        justify-content: space-between;
    }
    .message-content {
        white-space: pre-wrap;
        overflow-wrap: break-word;
    }
    .tool-call {
        margin-top: 10px;
        padding: 8px;
        background-color: #f8f9fa;
        border-radius: 4px;
    }
    .tool-message {
        background-color: #e6ffe6;  /* Light green background */
        border-left: 4px solid #28a745;  /* Darker green border */
        color: #000000;
    }
    /* Make all text monospace */
    .transcript-container, .message-container, .message-header,
    .message-content, .tool-call, h2, h3 {
        font-family: 'Courier New', Courier, monospace;
    }
</style>"""

        def format_message_html(index: int, message: ChatMessage) -> str:
            role = message.role
            content = message.text
            role_class = f"{role}-message"

            # Handle tool calls
            tool_call_html = ""
            if isinstance(message, ChatMessageAssistant) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if tool_call.view:
                        tool_call_html += f'<div class="tool-call">{tool_call.view.content}</div>'
                    else:
                        args = ", ".join([f"{k}={v}" for k, v in tool_call.arguments.items()])
                        tool_call_html += (
                            f'<div class="tool-call">{tool_call.function}({args})</div>'
                        )

            return f'<div class="message-container {role_class}">\n<div class="message-header"><span>Block {index} | {role.capitalize()}</span><span>ID: B{index}</span></div>\n<div class="message-content">{content}{tool_call_html}</div>\n</div>'

        messages_html = "\n".join([format_message_html(i, m) for i, m in enumerate(self.messages)])

        return f'{css}\n<div class="transcript-container">\n<h3>Chat Transcript</h3>\n{messages_html}\n</div>'


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
