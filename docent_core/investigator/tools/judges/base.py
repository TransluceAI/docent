from abc import ABC
from typing import AsyncIterator

from docent.data_models.chat.message import ChatMessage
from docent_core.investigator.tools.common.types import Grade, GradeEnd, GradeStart, GradeUpdate


class JudgeBase(ABC):
    """Base class for grading conversations.

    Subclasses can override either method:
    - Override `grade_transcript` only: The base `grade_transcript_stream` will call it
      and wrap the result in streaming events.
    - Override `grade_transcript_stream` only: The base `grade_transcript` will call it
      and extract the final Grade from the stream.
    - Override both: Each method uses its own implementation independently.

    Note: At least one method must be overridden by subclasses to avoid infinite recursion.
    """

    async def grade_transcript(self, conversation_history: list[ChatMessage]) -> Grade:
        """Grade a transcript for the target behavior.

        Default implementation calls grade_transcript_stream and extracts the final Grade.
        Subclasses can override this to provide a direct (non-streaming) implementation.
        """
        # Check if this method was overridden
        if type(self).grade_transcript_stream == JudgeBase.grade_transcript_stream:
            # grade_transcript_stream was NOT overridden, but this method also wasn't
            # This means neither method was overridden - raise an error
            raise NotImplementedError(
                "Subclasses must override at least one of grade_transcript or grade_transcript_stream"
            )

        # Call the streaming version and collect the final result
        final_grade = None
        async for event in self.grade_transcript_stream(conversation_history):
            if isinstance(event, GradeEnd):
                final_grade = event.annotation

        if final_grade is None:
            raise ValueError("grade_transcript_stream did not yield a GradeEnd event")

        return final_grade

    async def grade_transcript_stream(
        self, conversation_history: list[ChatMessage]
    ) -> AsyncIterator[GradeStart | GradeUpdate | GradeEnd]:
        """Grade a transcript with streaming updates.

        Default implementation calls grade_transcript and wraps the result in streaming events.
        Subclasses can override this to provide a true streaming implementation.

        This is useful when grading can't be done in a streaming manner (e.g. for string
        elicitation). In that case, child classes can just override `grade_transcript`.
        """
        # Check if this method was overridden
        if type(self).grade_transcript == JudgeBase.grade_transcript:
            # grade_transcript was NOT overridden, but this method also wasn't
            # This means neither method was overridden - raise an error
            raise NotImplementedError(
                "Subclasses must override at least one of grade_transcript or grade_transcript_stream"
            )

        yield GradeStart()
        annotation = await self.grade_transcript(conversation_history)
        yield GradeUpdate(content=annotation.grader_response)
        yield GradeEnd(annotation=annotation)
