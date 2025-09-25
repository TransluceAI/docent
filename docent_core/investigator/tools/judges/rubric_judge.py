"""
Implementation of a rubric judge.
This primitive takes in a transcript and a rubric, and returns a judge result.

TODO(neil): This should eventually be merged with Docent's judge primitive, rather than
being a separate class. For simplicity, we are keeping it separate for now.
"""

import json
import re
from contextlib import AbstractAsyncContextManager
from textwrap import dedent
from typing import AsyncIterator, Callable

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

from docent.data_models.chat.message import AssistantMessage, ChatMessage, UserMessage
from docent_core.investigator.db.schemas.experiment import SQLAJudgeConfig
from docent_core.investigator.tools.common.types import Grade, GradeEnd, GradeStart, GradeUpdate
from docent_core.investigator.tools.judges.base import JudgeBase


class RubricJudgeConfig(BaseModel):
    """Config for a rubric judge."""

    rubric: str
    model: str
    min_score: int
    max_score: int
    max_completion_tokens: int

    @classmethod
    def from_sql(cls, config: SQLAJudgeConfig) -> "RubricJudgeConfig":
        return cls(
            rubric=config.rubric,
            model="claude-sonnet-4-20250514",  # TODO(neil): make this configurable
            min_score=0,
            max_score=10,
            max_completion_tokens=500,
        )

    def build(
        self, client: AsyncOpenAI, limiter: Callable[[], AbstractAsyncContextManager[None]]
    ) -> "RubricJudge":
        return RubricJudge(
            rubric=self.rubric,
            client=client,
            limiter=limiter,
            model=self.model,
            min_score=self.min_score,
            max_score=self.max_score,
            max_completion_tokens=self.max_completion_tokens,
        )


class RubricJudge(JudgeBase):
    """Judge that uses a rubric to evaluate transcripts."""

    def __init__(
        self,
        rubric: str,
        client: AsyncOpenAI,
        limiter: Callable[[], AbstractAsyncContextManager[None]],
        model: str = "claude-sonnet-4-20250514",
        min_score: int = 0,
        max_score: int = 10,
        max_completion_tokens: int = 500,
    ) -> None:
        self.model = model
        self.rubric = rubric
        self.limiter = limiter
        self.min_score = min_score
        self.max_score = max_score
        self.client = client
        self.max_completion_tokens = max_completion_tokens

        self.grader_prompt = dedent(
            f"""
        You are evaluating a conversation using the following rubric:
        {self.rubric}

        Please analyze the conversation and provide:
        1. A score from {self.min_score} to {self.max_score} indicating how strongly the behavior was exhibited ({self.min_score} = not at all, {self.max_score} = very strongly)
        2. A brief explanation of your reasoning

        Conversation:
        {{conversation_text}}

        Please respond in the following format:
        SCORE: [{self.min_score}-{self.max_score}]
        REASONING: [Your explanation]""".strip()
        )

        assert self.min_score <= self.max_score, "Min score must be less than or equal to max score"

    async def grade_transcript_stream(
        self, conversation_history: list[ChatMessage]
    ) -> AsyncIterator[GradeStart | GradeUpdate | GradeEnd]:

        # Format the transcript, including tool calls if present
        conversation_parts: list[str] = []
        for msg in conversation_history:
            # Add the main message content
            conversation_parts.append(f"{msg.role.upper()}: {msg.content}")

            # If this is an assistant message with tool calls, add them
            if isinstance(msg, AssistantMessage) and msg.tool_calls:
                for tool_call in msg.tool_calls:
                    # Format the tool call
                    tool_call_str = f"  [TOOL CALL: {tool_call.function}("

                    # Format arguments as JSON for clarity
                    try:
                        args_str = json.dumps(tool_call.arguments, indent=2)
                        # Indent each line for better formatting
                        args_str = "\n".join("    " + line for line in args_str.split("\n"))
                        tool_call_str += f"\n{args_str}\n  "
                    except (TypeError, ValueError):
                        # Fallback to string representation if JSON fails
                        tool_call_str += str(tool_call.arguments)

                    tool_call_str += ")]"
                    conversation_parts.append(tool_call_str)

        conversation_text = "\n\n".join(conversation_parts)

        grader_prompt_formatted = self.grader_prompt.format(conversation_text=conversation_text)
        grader_response = ""

        @retry(stop=stop_after_attempt(5), wait=wait_exponential(multiplier=1, min=4, max=10))
        async def create_stream():
            async with self.limiter():
                return await self.client.chat.completions.create(
                    model=self.model,
                    max_completion_tokens=self.max_completion_tokens,
                    messages=[
                        {
                            "role": "user",
                            "content": grader_prompt_formatted,
                        }
                    ],
                    stream=True,
                )

        stream = await create_stream()

        yield GradeStart()

        async for chunk in stream:
            if chunk.choices[0].delta.content is not None:
                yield GradeUpdate(
                    content=chunk.choices[0].delta.content,  # type: ignore
                )
                grader_response += chunk.choices[0].delta.content  # type: ignore

        score_match = re.search(r"SCORE:\s*(\d+)", grader_response)
        if not score_match:
            raise ValueError(f"Could not extract score from grader response: {grader_response}")
        score = float(score_match.group(1))
        if not self.min_score <= score <= self.max_score:
            raise ValueError(
                f"Score {score} is outside expected range [{self.min_score}, {self.max_score}]"
            )

        annotation = Grade(
            grade=score,
            grader_prompt=[UserMessage(content=grader_prompt_formatted)],
            grader_response=grader_response,
        )

        yield GradeEnd(annotation=annotation)
