"""Utilities for computing signatures for experiment state change detection."""

from __future__ import annotations

import hashlib

from docent.data_models import AgentRun
from docent.data_models.chat import ContentReasoning, ContentText


def update_hash_with_agent_run(
    h: hashlib._Hash,  # type: ignore[misc]
    run: AgentRun,
) -> None:
    """Update a hash with agent run transcript data.

    This tracks message counts and content lengths for change detection during streaming.
    Handles both string content and Content block lists (for assistant messages).

    Args:
        h: The hash object to update (e.g., from hashlib.md5())
        run: The agent run to hash
    """
    if not run.transcripts:
        return

    for transcript in run.transcripts:
        h.update(transcript.id.encode())
        h.update(str(len(transcript.messages)).encode())

        if transcript.messages:
            last_msg = transcript.messages[-1]

            if isinstance(last_msg.content, str):
                # String content (for user, system, tool messages)
                h.update(str(len(last_msg.content)).encode())
            elif isinstance(last_msg.content, list):  # type: ignore[reportUnknownArgumentType]
                # Content blocks (for assistant messages with reasoning/text)
                total_content_length = 0
                for block in last_msg.content:
                    if isinstance(block, ContentText):
                        total_content_length += len(block.text)
                    elif isinstance(block, ContentReasoning):  # type: ignore[reportUnknownArgumentType]
                        total_content_length += len(block.reasoning)
                h.update(str(total_content_length).encode())
