"""
A simple judge that always returns a constant score.

This is useful for testing and baseline comparisons.
"""

from pydantic import BaseModel

from docent.data_models.chat.message import ChatMessage
from docent_core.investigator.tools.common.types import Grade
from docent_core.investigator.tools.judges.base import JudgeBase


class ConstantJudge(JudgeBase):
    """A judge that always returns the same constant score.

    This judge is useful for:
    - Testing judge infrastructure
    - Creating baseline comparisons
    - Debugging experiment pipelines
    """

    def __init__(
        self,
        score: float,
    ) -> None:
        """Initialize the constant judge.

        Args:
            score: The constant score to return for all transcripts.
        """
        self.score = score

    async def grade_transcript(self, conversation_history: list[ChatMessage]) -> Grade:
        """Return a constant grade regardless of the conversation content.

        Since we only implement this method, the base class will automatically
        provide grade_transcript_stream that wraps this result in streaming events.
        """

        return Grade(
            grade=self.score,
            grader_prompt=[],
            grader_response="",
        )


class ConstantJudgeConfig(BaseModel):
    score: float

    def build(self) -> ConstantJudge:
        return ConstantJudge(self.score)
