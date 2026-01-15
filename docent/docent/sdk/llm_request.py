from typing import Any

from pydantic import BaseModel

from docent.sdk.llm_context import PromptData


class LLMRequest(BaseModel):
    """Represents a request for LLM analysis of agent runs/transcripts.

    Example:
        from docent.sdk.llm_context import Prompt, AgentRunRef
        run = AgentRunRef(id="...", collection_id="...")

        # Simple case - \\n\\n added automatically between segments
        request = LLMRequest(prompt=Prompt([run, "Summarize this run."]))

        # Interspersed
        request = LLMRequest(prompt=Prompt([
            "Here is a successful run:", run1,
            "Here is a failed run:", run2,
            "Compare them."
        ]))

        # Reference same item multiple times
        request = LLMRequest(prompt=Prompt([
            "Consider this run:", run,
            "Notice that ", run, " exhibits interesting behavior."
        ]))
    """

    prompt: PromptData
    metadata: dict[str, Any] | None = None


class ExternalAnalysisResult(BaseModel):
    """Result of run analysis from an external source."""

    request: LLMRequest
    output: dict[str, Any]
