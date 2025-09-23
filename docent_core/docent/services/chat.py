import traceback
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncContextManager, AsyncIterator, Callable, Protocol, cast
from uuid import uuid4

import tiktoken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from docent.data_models.citation import (
    parse_citations,
)
from docent.data_models.remove_invalid_citation_ranges import remove_invalid_citation_ranges
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES, ModelOption
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    enqueue_job,
    get_redis_client,
)
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.ai_tools.assistant.chat import (
    create_add_label_tool,
    execute_add_label,
    make_system_prompt,
)
from docent_core.docent.ai_tools.rubric.rubric import JudgeRunLabel, Rubric
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.chat import ChatSession, SQLAChatSession
from docent_core.docent.db.schemas.tables import JobStatus, SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService

logger = get_logger(__name__)


class ChatEventCallback(Protocol):
    async def __call__(self, session: ChatSession):
        pass


def parse_suggestions(content: str, streaming: bool) -> tuple[str, list[str]]:
    """Parse suggestions from assistant message content.

    Args:
        content: The message content that may contain suggestions

    Returns:
        Tuple of (cleaned_content, suggestions_list)
    """
    import re

    if streaming:
        # Hide an unclosed <SUGGESTIONS> while streaming
        try:
            suggestions_start_idx = content.index("<SUGGESTIONS>")
            cleaned_content = content[:suggestions_start_idx]
        except ValueError:
            cleaned_content = content
        return cleaned_content, []

    pattern = r"<SUGGESTIONS>\s*(.*?)\s*</SUGGESTIONS>"
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)

    if not match:
        return content, []

    # Extract suggestions block
    suggestions_text = match.group(1).strip()

    # Remove the suggestions block from content
    cleaned_content = re.sub(pattern, "", content, flags=re.DOTALL | re.IGNORECASE).strip()

    # Parse individual suggestions (lines starting with -)
    suggestions: list[str] = []
    for line in suggestions_text.split("\n"):
        line = line.strip()
        if line.startswith("-"):
            suggestion = line[1:].strip()
            if suggestion:
                suggestions.append(suggestion)

    return cleaned_content, suggestions


def _parse_citations_in_messages(
    messages: list[ChatMessage], run: AgentRun, streaming: bool = False
) -> list[ChatMessage]:
    """Parse citations and suggestions in assistant messages and return updated messages."""

    parsed_messages: list[ChatMessage] = []

    for message in messages:
        if message.role == "assistant":
            try:
                # Parse suggestions first, then citations from the content
                content_text = message.text
                cleaned_text_suggestions, suggestions = parse_suggestions(content_text, streaming)
                cleaned_text, citations = parse_citations(cleaned_text_suggestions)

                # Create new message with parsed citations and suggestions
                updated_message = AssistantMessage(
                    id=message.id,
                    content=cleaned_text,
                    model=message.model,
                    tool_calls=message.tool_calls,
                    citations=citations,
                    suggested_messages=suggestions if suggestions else None,
                )
                parsed_messages.append(updated_message)
            except Exception as e:
                logger.warning(
                    f"Failed to parse citations and suggestions from assistant message: {e}"
                )
                parsed_messages.append(message)
        else:
            parsed_messages.append(message)

    return parsed_messages


class ChatService:
    def __init__(
        self,
        session: AsyncSession,
        session_cm_factory: Callable[[], AsyncContextManager[AsyncSession]],
        mono_svc: MonoService,
        rubric_svc: RubricService,
    ):
        self.session = session
        self.session_cm_factory = session_cm_factory
        self.mono_svc = mono_svc
        self.rubric_svc = rubric_svc

    async def get_session_by_id(self, session_id: str) -> SQLAChatSession | None:
        result = await self.session.execute(
            select(SQLAChatSession).where(
                SQLAChatSession.id == session_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_session_by_run(
        self, run_id: str, user_id: str, judge_result_id: str | None = None
    ):
        result = await self.session.execute(
            select(SQLAChatSession)
            .where(SQLAChatSession.agent_run_id == run_id)
            .where(SQLAChatSession.user_id == user_id)
            .where(SQLAChatSession.judge_result_id == judge_result_id)
            .order_by(SQLAChatSession.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_or_create_session(
        self,
        user_id: str,
        agent_run_id: str,
        judge_result_id: str | None = None,
        force_create: bool = False,
    ):
        # Use the first available chat model as default
        default_chat_model = PROVIDER_PREFERENCES.default_chat_models[0].model_dump()

        async with self.mono_svc.advisory_lock(agent_run_id, f"create_session_{agent_run_id}"):
            sqla_session: SQLAChatSession | None = None
            if not force_create:
                sqla_session = await self.get_session_by_run(agent_run_id, user_id, judge_result_id)
            if sqla_session is None:

                # Ensure required fields are initialized so the instance is usable pre-flush
                sqla_session = SQLAChatSession(
                    id=str(uuid4()),  # Explicitly set ID to avoid None during pre-flush usage
                    user_id=user_id,
                    agent_run_id=agent_run_id,
                    judge_result_id=judge_result_id,
                    messages=[],
                    chat_model=default_chat_model,
                )
                self.session.add(sqla_session)
            if sqla_session.chat_model is None:
                sqla_session.chat_model = default_chat_model
            return sqla_session

    async def _update_session(self, sqla_session: SQLAChatSession, messages: list[dict[str, Any]]):
        # Update the instance directly so its in-memory state is current
        sqla_session.messages = messages
        sqla_session.updated_at = datetime.now(UTC).replace(tzinfo=None)

    async def add_user_message(self, sqla_session: SQLAChatSession, message: str):
        await self._update_session(
            sqla_session, sqla_session.messages + [UserMessage(content=message).model_dump()]
        )

    async def update_session_chat_model(
        self, sqla_session: SQLAChatSession, chat_model: ModelOption
    ):
        """Update the chat model for this session."""
        sqla_session.chat_model = chat_model.model_dump()
        sqla_session.updated_at = datetime.now(UTC).replace(tzinfo=None)

    async def estimate_input_tokens(
        self, ctx: ViewContext, sqla_session: SQLAChatSession, encoding_name: str = "o200k_base"
    ) -> int:
        """Roughly estimate the number of input tokens that will be used for one_turn with this chat session."""
        session = sqla_session.to_pydantic()
        encoding = tiktoken.get_encoding(encoding_name)

        context_messages, _, _ = await self._get_chat_context(ctx, sqla_session, session.messages)

        # Convert to text format and count tokens
        total_tokens = 0
        for message in context_messages:
            total_tokens += len(encoding.encode(message.text))

            if isinstance(message, AssistantMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if hasattr(tool_call, "function") and hasattr(tool_call, "arguments"):
                        args_str = str(tool_call.arguments) if tool_call.arguments else ""
                        total_tokens += len(
                            encoding.encode(f"\nTool call: {tool_call.function}({args_str})")
                        )

            total_tokens += 10  # Add a small buffer for message formatting overhead

        return total_tokens

    async def get_current_state(
        self, ctx: ViewContext, sqla_session: SQLAChatSession
    ) -> ChatSession:
        """Return the current state of the chat session as a pydantic model with parsed citations."""
        session = sqla_session.to_pydantic()
        parsed_session = await self._parse_citations_in_session(ctx, session)
        if parsed_session.estimated_input_tokens is not None or sqla_session.agent_run_id is None:
            return parsed_session

        # If we have a run but no token usage data, estimate token count
        try:
            estimated_tokens = await self.estimate_input_tokens(ctx, sqla_session)
        except Exception as e:
            logger.warning(f"Failed to estimate input tokens for session {sqla_session.id}: {e}")
            estimated_tokens = None

        # Add estimated tokens to response
        return parsed_session.model_copy(update={"estimated_input_tokens": estimated_tokens})

    async def _parse_citations_in_session(
        self, ctx: ViewContext, session: ChatSession
    ) -> ChatSession:
        """Helper to parse citations in a chat session."""
        if not session.agent_run_id:
            return session

        agent_run = await self.mono_svc.get_agent_run(
            ctx, session.agent_run_id, apply_base_where_clause=False
        )
        if agent_run is None:
            return session

        # Parse citations in assistant messages
        parsed_messages = _parse_citations_in_messages(
            session.messages, run=agent_run, streaming=False
        )
        return session.model_copy(update={"messages": parsed_messages})

    @staticmethod
    async def _get_active_chat_job(session: AsyncSession, session_id: str) -> SQLAJob | None:
        result = await session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.CHAT_JOB.value)
            .where(SQLAJob.job_json["session_id"].astext == session_id)
            .where((SQLAJob.status == JobStatus.PENDING) | (SQLAJob.status == JobStatus.RUNNING))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_job_for_session(self, session_id: str) -> SQLAJob | None:
        return await self._get_active_chat_job(self.session, session_id)

    async def start_or_get_chat_job(self, ctx: ViewContext, sqla_session: SQLAChatSession):
        """This job is responsible for running the chat for one turn.
        Uses an advisory lock to avoid races where multiple jobs are started for the same session.
        """

        async with self.mono_svc.advisory_lock(
            sqla_session.id,
            f"start_chat_session_{sqla_session.id}",
        ):
            # Is there already a job for this session?
            existing_job = await self._get_active_chat_job(self.session, sqla_session.id)
            if existing_job:
                return existing_job.id

            # There is no running job, create a new one
            job_id = str(uuid4())
            self.session.add(
                SQLAJob(
                    id=job_id,
                    type=WorkerFunction.CHAT_JOB.value,
                    job_json={"session_id": sqla_session.id},
                )
            )

            # Exception to rule of not committing inside the service:
            #   commit so that the enqueued job is visible to the worker
            await self.session.commit()
            await enqueue_job(ctx, job_id)

            return job_id

    async def listen_for_job_state(self, job_id: str) -> AsyncIterator[ChatSession]:
        REDIS = await get_redis_client()
        stream_key = STREAM_KEY_FORMAT.format(job_id=job_id)
        state_key = STATE_KEY_FORMAT.format(job_id=job_id)

        """Yield authoritative state updates for a job by listening to its notifier stream.
        This function never errors and instead logs the error and continues.
        It exits when the job is finished.
        """

        async def _get_state():
            raw_state = await REDIS.get(state_key)  # type: ignore
            if raw_state is not None:
                return ChatSession.model_validate_json(raw_state)
            else:
                return None

        # Before anything else, push the state
        state = await _get_state()
        if state is not None:
            yield state

        # Start from the beginning so we don't miss a prior "finished" event
        # and advance the cursor on every read to avoid dropping intermediate events.
        last_id = "0-0"
        done = False

        while not done:
            # Block until a notifier event arrives
            try:
                results = await REDIS.xread({stream_key: last_id}, block=30000, count=1)  # type: ignore

                # Timed out waiting for events; loop again

                if not results:
                    continue

                for _stream, entries in results:
                    if len(entries) == 0:
                        continue
                    _entry_id, _data = entries[-1]

                    # Advance the cursor so we don't miss subsequent events
                    last_id = _entry_id
                    # Parse out the last event entry
                    data = cast(dict[str, str], _data)
                    logger.info(f"Job {job_id} received event data {data}")

                    # Only look at state_updated and finished events
                    event = data.get("event")
                    if event not in {"state_updated", "finished"}:
                        logger.error(f"Job {job_id} received unknown event {event}")
                        continue

                    # Regardless of whether we're done, push the state
                    state = await _get_state()
                    if state is not None:
                        yield state

                    # If done, return
                    if event == "finished":
                        done = True
                        break
            except Exception as e:
                logger.error(
                    f"Error reading from Redis stream {stream_key}: {e}. Traceback:\n{traceback.format_exc()}"
                )
                continue

    async def _get_chat_context(
        self,
        ctx: ViewContext,
        sqla_session: SQLAChatSession,
        messages: list[ChatMessage],
    ) -> tuple[list[ChatMessage], AgentRun, Rubric | None]:
        """Get chat context including system prompt, context messages, and related objects."""
        if sqla_session.agent_run_id is None:
            raise ValueError(f"Session {sqla_session.id} has no agent run")

        # Get agent run for system prompt and citation parsing
        agent_run = await self.mono_svc.get_agent_run(
            ctx, sqla_session.agent_run_id, apply_base_where_clause=False
        )
        if agent_run is None:
            raise ValueError(f"Agent run {sqla_session.agent_run_id} not found")

        # Get judge result if available
        judge_result = None
        if sqla_session.judge_result_id:
            judge_result = await self.rubric_svc.get_rubric_result_by_id(
                sqla_session.judge_result_id
            )

        # Get rubric from judge result if available
        rubric = None
        if judge_result:
            sqla_rubric = await self.rubric_svc.get_rubric(
                judge_result.rubric_id, judge_result.rubric_version
            )
            if sqla_rubric:
                rubric = sqla_rubric.to_pydantic()

        # Create system prompt
        system_prompt = make_system_prompt(
            agent_run=agent_run, judge_result=judge_result, rubric=rubric
        )

        # Create context messages
        context_messages = [SystemMessage(content=system_prompt)] + messages

        return context_messages, agent_run, rubric

    async def one_turn(
        self,
        ctx: ViewContext,
        sqla_session: SQLAChatSession,
        sse_callback: ChatEventCallback | None = None,
    ):
        """Run one turn of the chat assistant. Called by worker process, not API server.
        Executes tool calls (e.g., add_label) and streams intermediate state.
        """

        raw_chat_session = sqla_session.to_pydantic()

        context_messages, agent_run, rubric = await self._get_chat_context(
            ctx, sqla_session, raw_chat_session.messages
        )

        # Local working copy of raw messages (persisted form)
        # TODO(ryanbloom): maybe we should have separate types for raw + parsed messages
        raw_messages = raw_chat_session.messages.copy()

        async def _llm_streaming_callback(batch_index: int, llm_output: LLMOutput):
            if sse_callback and (completion := llm_output.first):
                if not completion.text:
                    return
                cleaned_text = remove_invalid_citation_ranges(completion.text, agent_run)
                assistant_msg = AssistantMessage(
                    content=cleaned_text,
                    tool_calls=completion.tool_calls,
                )

                # Derive parsed view for streaming without mutating/persisting parsed data
                parsed_for_stream = _parse_citations_in_messages(
                    raw_messages + [assistant_msg], run=agent_run, streaming=True
                )

                await sse_callback(
                    raw_chat_session.model_copy(update={"messages": parsed_for_stream})
                )

        logger.info(f"Running one turn of chat session: {sqla_session}")

        # Convert session's chat model to ModelOption
        if sqla_session.chat_model is not None:
            session_model = ModelOption.model_validate(sqla_session.chat_model)
        else:
            session_model = PROVIDER_PREFERENCES.default_chat_models[0]

        MAX_ITERS_PER_TURN = 5
        for _ in range(MAX_ITERS_PER_TURN):
            if len(raw_messages) == 0:
                break

            last_message = raw_messages[-1]

            # If the last message is an assistant message with no tool calls, break
            if last_message.role == "assistant" and not getattr(last_message, "tool_calls", None):
                break

            # If user or tool: generate assistant continuation
            if last_message.role in ("user", "tool"):
                tools = None if rubric is None else [create_add_label_tool(rubric.output_schema)]
                tool_choice = "auto" if rubric is not None else None

                # Recompute context with the latest messages to avoid repeating tool calls
                context_messages, _, _ = await self._get_chat_context(
                    ctx, sqla_session, raw_messages
                )

                outputs = await get_llm_completions_async(
                    [context_messages],
                    [session_model],
                    max_new_tokens=8192,
                    timeout=120.0,
                    use_cache=True,
                    streaming_callback=_llm_streaming_callback,
                    tools=tools,
                    tool_choice=tool_choice,
                    api_key_overrides=await self.mono_svc.get_api_key_overrides(ctx.user),
                )
                result = outputs[0]

                # Handle provider errors first by surfacing an error state via sse_callback
                if result.did_error:
                    error_state = raw_chat_session.model_copy(
                        update={"error_message": result.errors[0].user_message}
                    )
                    if sse_callback:
                        await sse_callback(error_state)
                    return error_state

                # Parse completion and append to messages
                completion = result.first
                if completion is None:
                    # Defensive fallback: treat as no-response error
                    error_state = raw_chat_session.model_copy(
                        update={
                            "error_message": "The model returned no response. Please try again."
                        }
                    )
                    if sse_callback:
                        await sse_callback(error_state)
                    return error_state

                cleaned_text = remove_invalid_citation_ranges(completion.text or "", agent_run)
                assistant_msg = AssistantMessage(
                    content=cleaned_text, tool_calls=completion.tool_calls
                )
                raw_messages.append(assistant_msg)

                # Store real token count from API response if available
                if result.total_tokens is not None:
                    sqla_session.estimated_input_tokens = result.total_tokens

            # If assistant with tool calls: execute tool calls
            elif last_message.role == "assistant" and (tool_calls := last_message.tool_calls):
                for tc in tool_calls:
                    try:
                        if tc.function == "add_label" and rubric is not None:
                            tool_result_msg = execute_add_label(rubric, tc)

                            if tool_result_msg.content == "No label provided.":
                                raw_messages.append(tool_result_msg)
                                continue

                            # TODO(cadentj): Maybe check there's only one key
                            label_dict = tc.arguments.get("label", {})

                            agent_run_id = agent_run.id
                            existing = await self.rubric_svc.get_judge_run_label(agent_run_id)

                            # Create a new label if it doesn't exist, else update the existing one
                            if existing is None:
                                await self.rubric_svc.create_judge_run_label(
                                    JudgeRunLabel(
                                        agent_run_id=agent_run_id,
                                        rubric_id=rubric.id,
                                        label=label_dict,
                                    )
                                )
                            else:
                                merged = dict(existing.label)
                                merged.update(label_dict)
                                await self.rubric_svc.update_judge_run_label(agent_run_id, merged)

                            raw_messages.append(tool_result_msg)
                        else:
                            raise ValueError(f"Unsupported tool call: {tc.function}")
                    except Exception as e:
                        raw_messages.append(
                            ToolMessage(
                                content=f"Error executing tool call: {e}",
                                error={"detail": str(e)},
                                tool_call_id=tc.id,
                                function=tc.function,
                            )
                        )

            # Update session and notify
            await self._update_session(sqla_session, [m.model_dump() for m in raw_messages])
            await self.session.commit()

            # Push current state with parsed citations
            if sse_callback:
                parsed_messages = _parse_citations_in_messages(
                    raw_messages, run=agent_run, streaming=False
                )
                await sse_callback(
                    raw_chat_session.model_copy(update={"messages": parsed_messages})
                )

        # Final state (parsed for presentation)
        final_parsed = _parse_citations_in_messages(raw_messages, run=agent_run, streaming=False)
        return raw_chat_session.model_copy(update={"messages": final_parsed})

    async def cleanup_old_chat_sessions(self, days_old: int = 7) -> int:
        """
        Delete chat sessions that haven't been updated in the specified number of days.

        Args:
            days_old: Number of days after which sessions are considered old (default: 7)

        Returns:
            Number of sessions deleted
        """
        cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_old)

        result = await self.session.execute(
            delete(SQLAChatSession).where(SQLAChatSession.updated_at < cutoff_date)
        )
        # Ensure the deletion is persisted
        await self.session.commit()
        deleted_count = result.rowcount or 0
        return deleted_count
