from datetime import UTC, datetime
from typing import Any, AsyncContextManager, Callable

import anyio
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.chat.message import AssistantMessage, ChatMessage, ToolMessage
from docent.data_models.chat.tool import ToolCall
from docent_core._ai_tools.refinement.refinement import (
    REFINEMENT_TOOLS,
    SYSTEM_PROMPT,
    execute_add_rubric_rule,
    execute_update_description,
    execute_update_rule,
    format_conversation_for_client,
)
from docent_core._db_service.schemas.refinement import SQLARefinementSession
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core.docent.ai_tools.rubric.rubric import Rubric
from docent_core.docent.services.monoservice import MonoService

logger = get_logger(__name__)


class RefinementService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        service: MonoService,
    ):
        """The `session_cm_factory` creates new sessions that commit writes immediately.
        This is helpful if you don't want to wait for results to be written."""

        self.session = session
        self.session_cm_factory = session_cm_factory
        self.service = service

    async def get_refinement_session(self, rubric_id: str) -> SQLARefinementSession | None:
        result = await self.session.execute(
            select(SQLARefinementSession).where(
                SQLARefinementSession.rubric_id == rubric_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_refinement_session(
        self, collection_id: str, rubric_id: str
    ) -> SQLARefinementSession:
        # Create new session
        refinement_session = SQLARefinementSession(
            collection_id=collection_id,
            rubric_id=rubric_id,
            messages=[{"role": "system", "content": SYSTEM_PROMPT}],
        )
        self.session.add(refinement_session)
        await self.session.commit()
        return refinement_session

    async def clear_refinement_session(self, rubric_id: str):
        await self.session.execute(
            update(SQLARefinementSession)
            .where(SQLARefinementSession.rubric_id == rubric_id)
            .values(messages=[{"role": "system", "content": SYSTEM_PROMPT}])
        )
        await self.session.commit()

    async def _execute_tool_call(self, tool_call: ToolCall, rubric: Rubric) -> str | None:

        if tool_call.function == "updateDescription":
            return execute_update_description(rubric, tool_call)
        elif tool_call.function == "addRubricRule":
            return execute_add_rubric_rule(rubric, tool_call)
        elif tool_call.function == "updateRubric":
            return execute_update_rule(rubric, tool_call)
        raise ValueError(f"Unsupported tool call: {tool_call.function}")

    async def _update_messages(self, rubric_id: str, messages: list[ChatMessage]):
        serializable_messages = [message.model_dump() for message in messages]

        await self.session.execute(
            update(SQLARefinementSession)
            .where(SQLARefinementSession.rubric_id == rubric_id)
            .values(
                messages=serializable_messages, updated_at=datetime.now(UTC).replace(tzinfo=None)
            )
        )
        await self.session.commit()

    async def get_assistant_response(
        self, rubric_id: str, messages: list[ChatMessage], rubric: Rubric
    ):
        continuation_message: ChatMessage | None = None
        send_channel, receive_channel = anyio.create_memory_object_stream[dict[str, Any] | None](
            max_buffer_size=100
        )

        def _create_state_update(rubric_update: bool = False) -> dict[str, Any]:
            nonlocal continuation_message

            current_messages = messages[1:]
            if continuation_message is not None:
                current_messages.append(continuation_message)

            current_messages = format_conversation_for_client(current_messages, serialize=True)

            body: dict[str, Any] = {
                "messages": current_messages,
            }
            if rubric_update:
                body["rubric"] = rubric.model_dump()

            return body

        async def _llm_callback(batch_index: int, llm_output: LLMOutput):
            nonlocal continuation_message
            text = llm_output.first_text
            if text:
                continuation_message = AssistantMessage(content=text)
                # Queue the token update for streaming
                await send_channel.send(_create_state_update())

        async def _run_llm_generation():
            nonlocal continuation_message

            while True:
                try:
                    response = await get_llm_completions_async(
                        [messages],
                        PROVIDER_PREFERENCES.handle_refinement_message,
                        max_new_tokens=2048,
                        timeout=180.0,
                        tools=REFINEMENT_TOOLS,
                        tool_choice="auto",
                        streaming_callback=_llm_callback,
                        use_cache=True,
                    )

                    completions = response[0].completions
                    text = completions[0].text
                    tool_calls = completions[0].tool_calls

                    if text is None:
                        logger.critical(f"No text found in response: {response}")
                        text = "..."

                    messages.append(
                        AssistantMessage(
                            content=text,
                            tool_calls=tool_calls,
                        )
                    )

                    await self._update_messages(rubric_id, messages)

                    if tool_calls and len(tool_calls) > 0:
                        for tool_call in tool_calls:
                            result = await self._execute_tool_call(tool_call, rubric)

                            if result is None:
                                raise ValueError(f"Tool call had no result: {tool_call}")

                            tool_message = ToolMessage(
                                content=result,
                                tool_call_id=tool_call.id,
                                function=tool_call.function,
                                error=None,
                            )

                            messages.append(tool_message)
                            continuation_message = tool_message

                            await self._update_messages(rubric_id, messages)

                            # Handle special cases
                            if "Started search job" in result:
                                job_id = result.split(": ")[1]
                                await send_channel.send({"search_job": job_id})
                            else:
                                # TODO(caden): this assumes all tool calls update the rubric
                                await send_channel.send(_create_state_update(rubric_update=True))
                    else:
                        # No more tool calls, we're done
                        break

                except Exception as e:
                    logger.error(f"Error in LLM generation: {e}")
                    await send_channel.send({"error": str(e)})
                    break

            # Signal completion
            await send_channel.aclose()

        # Send initial state
        yield _create_state_update()

        # Start LLM generation in background
        async with anyio.create_task_group() as tg:
            tg.start_soon(_run_llm_generation)

            # Consumer loop - yield updates from stream
            async with receive_channel:
                async for update in receive_channel:
                    yield update
