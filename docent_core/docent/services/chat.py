import traceback
from datetime import UTC, datetime, timedelta
from typing import Any, AsyncContextManager, AsyncIterator, Callable, Protocol, cast
from uuid import uuid4

import tiktoken
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.providers.preference_types import ModelOption
from docent._log_util import get_logger
from docent.data_models.agent_run import SelectionSpec
from docent.data_models.chat.message import (
    AssistantMessage,
    DocentAssistantMessage,
    DocentChatMessage,
    SystemMessage,
    UserMessage,
)
from docent.sdk.llm_context import (
    AgentRunRef,
    LLMContext,
    LLMContextSpec,
    TranscriptRef,
    resolve_citations_with_context,
)
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    enqueue_job,
    get_redis_client,
)
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.ai_tools.assistant.chat import (
    make_system_prompt,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.chat import ChatSession, ChatSessionSummary, SQLAChatSession
from docent_core.docent.db.schemas.tables import (
    JobStatus,
    SQLAAgentRun,
    SQLAJob,
    SQLATranscript,
)
from docent_core.docent.services.label import LabelService
from docent_core.docent.services.llms import PROVIDER_PREFERENCES, LLMService
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService
from docent_core.docent.utils.llm_context import (
    compute_context_token_estimates,
    load_context_objects,
)

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
    messages: list[DocentChatMessage],
    context: LLMContext,
    streaming: bool = False,
) -> list[DocentChatMessage]:
    """Parse citations and suggestions in assistant messages and return updated messages.

    Args:
        messages: List of messages to parse
        context: LLMContext for resolving citations
        streaming: Whether messages are being streamed
    """
    parsed_messages: list[DocentChatMessage] = []

    for message in messages:
        if isinstance(message, DocentAssistantMessage):
            try:
                # Parse suggestions first, then citations from the content
                content_text = message.text
                cleaned_text_suggestions, suggestions = parse_suggestions(content_text, streaming)

                # Parse citations based on context type
                cleaned_text, citations = resolve_citations_with_context(
                    cleaned_text_suggestions, context
                )

                # Create new message with parsed citations and suggestions
                updated_message = DocentAssistantMessage(
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
        label_svc: LabelService,
        llm_svc: LLMService,
    ):
        self.session = session
        self.session_cm_factory = session_cm_factory
        self.mono_svc = mono_svc
        self.rubric_svc = rubric_svc
        self.label_svc = label_svc
        self.llm_svc = llm_svc

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

        context_messages, _ = await self._get_chat_context(ctx, sqla_session, session.messages)

        # Convert to text format and count tokens
        total_tokens = 0
        for message in context_messages:
            total_tokens += len(encoding.encode(message.text, disallowed_special=()))

            if isinstance(message, AssistantMessage) and message.tool_calls:
                for tool_call in message.tool_calls:
                    if hasattr(tool_call, "function") and hasattr(tool_call, "arguments"):
                        args_str = str(tool_call.arguments) if tool_call.arguments else ""
                        total_tokens += len(
                            encoding.encode(
                                f"\nTool call: {tool_call.function}({args_str})",
                                disallowed_special=(),
                            )
                        )

            total_tokens += 10  # Add a small buffer for message formatting overhead

        return total_tokens

    async def get_chat_sessions_for_run(
        self, collection_id: str, agent_run_id: str
    ) -> list[ChatSession]:
        result = await self.session.execute(
            select(SQLAChatSession)
            .join(SQLAAgentRun, SQLAChatSession.agent_run_id == SQLAAgentRun.id)
            .where(SQLAAgentRun.collection_id == collection_id)
            .where(SQLAChatSession.agent_run_id == agent_run_id)
            .where(SQLAChatSession.judge_result_id.is_(None))
            .order_by(SQLAChatSession.updated_at.desc())
        )
        return [sqla_session.to_pydantic() for sqla_session in result.scalars().all()]

    async def lookup_context_item(self, item_id: str) -> AgentRunRef | TranscriptRef | None:
        """Return item info for a transcript or agent run id, else None."""
        agent_run = await self.session.execute(
            select(SQLAAgentRun.collection_id).where(SQLAAgentRun.id == item_id)
        )
        collection_id = agent_run.scalar_one_or_none()
        if collection_id:
            return AgentRunRef(id=item_id, collection_id=str(collection_id))

        transcript = await self.session.execute(
            select(SQLATranscript.agent_run_id, SQLAAgentRun.collection_id)
            .join(SQLAAgentRun, SQLAAgentRun.id == SQLATranscript.agent_run_id)
            .where(SQLATranscript.id == item_id)
        )
        transcript_row = transcript.first()
        if transcript_row:
            transcript_agent_run_id, transcript_collection_id = transcript_row
            return TranscriptRef(
                id=item_id,
                agent_run_id=str(transcript_agent_run_id),
                collection_id=str(transcript_collection_id),
            )

        return None

    async def add_context_item(self, sq_chat_session: SQLAChatSession, item_id: str) -> ChatSession:
        if sq_chat_session.context_serialized is None:
            raise ValueError("Cannot add context item to a session without context")

        lookup = await self.lookup_context_item(item_id)
        if lookup is None:
            raise ValueError(f"Item {item_id} not found")

        if sq_chat_session.collection_id and sq_chat_session.collection_id != lookup.collection_id:
            raise ValueError("Item collection does not match session collection")

        spec = LLMContextSpec.model_validate(sq_chat_session.context_serialized)

        if lookup.type == "agent_run":
            agent_runs = await self.mono_svc.get_agent_runs(
                ctx=None, agent_run_ids=[item_id], apply_base_filter=False
            )
            if not agent_runs:
                raise ValueError(f"Agent run {item_id} not found")

            agent_run = agent_runs[0]
            _ = spec.add_agent_run_from_object(
                agent_run=agent_run,
                collection_id=lookup.collection_id,
            )

        else:
            assert isinstance(lookup, TranscriptRef)
            _ = spec.add_transcript(
                id=item_id,
                agent_run_id=lookup.agent_run_id,
                collection_id=lookup.collection_id,
                is_root=True,
            )

        sq_chat_session.context_serialized = spec.to_dict()
        return sq_chat_session.to_pydantic()

    async def remove_context_item(
        self, sq_chat_session: SQLAChatSession, item_id: str
    ) -> ChatSession:
        if sq_chat_session.context_serialized is None:
            raise ValueError("Cannot remove context item from a session without context")

        spec = LLMContextSpec.model_validate(sq_chat_session.context_serialized)

        target_alias: str | None = None
        for alias, ref in spec.items.items():
            if ref.id == item_id and alias in spec.root_items:
                target_alias = alias
                break

        if target_alias is None:
            raise ValueError(f"Item {item_id} not in context")

        spec.remove_from_root(target_alias)
        sq_chat_session.context_serialized = spec.to_dict()
        return sq_chat_session.to_pydantic()

    async def update_context_item(
        self,
        sq_chat_session: SQLAChatSession,
        agent_run_id: str,
        selection_spec: SelectionSpec | None,
        visible: bool | None,
    ) -> ChatSession:
        if sq_chat_session.context_serialized is None:
            raise ValueError("Cannot update context without context_serialized")

        spec = LLMContextSpec.model_validate(sq_chat_session.context_serialized)

        target_alias: str | None = None
        for alias, ref in spec.items.items():
            if ref.id == agent_run_id:
                target_alias = alias
                break

        if target_alias is None:
            raise ValueError(f"Item {agent_run_id} not in context")

        if selection_spec is not None:
            spec.set_selection_spec(target_alias, selection_spec)

        if visible is not None:
            if target_alias not in spec.root_items:
                raise ValueError("Visibility toggle only applies to root items")
            spec.set_visibility(target_alias, visible)

        sq_chat_session.context_serialized = spec.to_dict()
        return sq_chat_session.to_pydantic()

    async def get_conversations_for_collection(
        self, user_id: str, collection_id: str
    ) -> list[ChatSession]:
        result = await self.session.execute(
            select(SQLAChatSession)
            .where(SQLAChatSession.user_id == user_id)
            .where(SQLAChatSession.collection_id == collection_id)
            .where(SQLAChatSession.context_serialized.is_not(None))
            .order_by(SQLAChatSession.updated_at.desc())
        )
        return [sqla_session.to_pydantic() for sqla_session in result.scalars().all()]

    async def get_conversation_summaries_for_collection(
        self, user_id: str, collection_id: str
    ) -> list[ChatSessionSummary]:
        result = await self.session.execute(
            select(SQLAChatSession)
            .where(SQLAChatSession.user_id == user_id)
            .where(SQLAChatSession.collection_id == collection_id)
            .where(SQLAChatSession.context_serialized.is_not(None))
            .order_by(SQLAChatSession.updated_at.desc())
        )
        return [sqla_session.to_summary() for sqla_session in result.scalars().all()]

    async def create_conversation_session(
        self,
        user_id: str,
        context_serialized: dict[str, Any],
        chat_model: ModelOption | None = None,
        collection_id: str | None = None,
    ) -> SQLAChatSession:
        if chat_model is None:
            chat_model = PROVIDER_PREFERENCES.default_chat_models[0]
        sqla_session = SQLAChatSession(
            id=str(uuid4()),
            user_id=user_id,
            collection_id=collection_id,
            agent_run_id=None,
            judge_result_id=None,
            context_serialized=context_serialized,
            messages=[],
            chat_model=chat_model.model_dump() if chat_model else None,
        )
        self.session.add(sqla_session)
        await self.session.flush()
        return sqla_session

    async def delete_session(self, sqla_session: SQLAChatSession) -> None:
        await self.session.delete(sqla_session)

    async def get_current_state(
        self, ctx: ViewContext | None, sqla_session: SQLAChatSession
    ) -> ChatSession:
        """Return the current state of the chat session as a pydantic model.

        For "chat with anything" sessions (context_serialized != None), citations are already
        parsed and stored in the database. Token estimates are computed for visible items.
        For existing single-run chats (context_serialized == None), citations need to be parsed.
        """
        session = sqla_session.to_pydantic()

        # Handle multi-run sessions with context_serialized
        # PERF: This loads items and computes estimates on every call.
        if session.context_serialized is not None:
            session = await self._compute_multi_run_token_estimates(sqla_session, session)
            return session

        # Handle single-run sessions
        if session.agent_run_id is not None and ctx is not None:
            session = await self._parse_citations_in_session(ctx, session)

        if session.estimated_input_tokens is not None or sqla_session.agent_run_id is None:
            return session

        # If we have a run but no token usage data, estimate token count
        # (only for single-run sessions)
        if ctx is None:
            return session

        try:
            estimated_tokens = await self.estimate_input_tokens(ctx, sqla_session)
        except Exception as e:
            logger.warning(f"Failed to estimate input tokens for session {sqla_session.id}: {e}")
            estimated_tokens = None

        # Add estimated tokens to response
        return session.model_copy(update={"estimated_input_tokens": estimated_tokens})

    async def _compute_multi_run_token_estimates(
        self, sqla_session: SQLAChatSession, session: ChatSession
    ) -> ChatSession:
        """Compute token estimates for multi-run chat sessions.

        PERF: This loads context items and computes estimates on every call.
        """
        try:
            spec = LLMContextSpec.model_validate(sqla_session.context_serialized)  # type: ignore
            context = await load_context_objects(spec, self.mono_svc)

            # Compute per-item estimates
            item_estimates = compute_context_token_estimates(context)

            # Sum visible items for total context estimate
            visible_context_tokens = sum(
                item_estimates.get(alias, 0)
                for alias in context.root_items
                if context.item_visibility.get(alias, True)
            )

            # Compute total estimate using ground truth anchor if available
            if sqla_session.estimated_messages_tokens is not None:
                # We have ground truth from a previous API call
                # estimated_messages_tokens = ground_truth - context_estimate_at_call_time
                # So total = base + current_visible_context
                total_estimate = sqla_session.estimated_messages_tokens + visible_context_tokens
            else:
                # No API call yet, estimate is just the visible context
                # (system prompt overhead is relatively small, we ignore it here)
                total_estimate = visible_context_tokens

            return session.model_copy(
                update={
                    "estimated_input_tokens": total_estimate,
                    "item_token_estimates": item_estimates,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to compute token estimates for session {sqla_session.id}: {e}")
            return session

    async def _parse_citations_in_session(
        self, ctx: ViewContext, session: ChatSession
    ) -> ChatSession:
        """Helper to parse citations for existing single-run chat sessions."""
        if not session.agent_run_id:
            return session

        # Skip the db query if no messages are missing citations
        has_unparsed_citations = False
        for message in session.messages:
            if message.role == "assistant" and getattr(message, "citations", None) is None:
                has_unparsed_citations = True
                break

        if not has_unparsed_citations:
            return session

        agent_run = await self.mono_svc.get_agent_run(
            ctx, session.agent_run_id, apply_base_where_clause=False
        )
        if agent_run is None:
            return session

        context = LLMContext(items=[agent_run])
        parsed_messages = _parse_citations_in_messages(session.messages, context)

        return session.model_copy(update={"messages": parsed_messages})

    @staticmethod
    async def _get_active_chat_job(session: AsyncSession, session_id: str) -> SQLAJob | None:
        result = await session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.CHAT_JOB.value)
            .where(SQLAJob.job_json["session_id"].astext == session_id)
            .where(SQLAJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING, JobStatus.CANCELLING]))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_job_for_session(self, session_id: str) -> SQLAJob | None:
        return await self._get_active_chat_job(self.session, session_id)

    async def start_or_get_chat_job(self, ctx: ViewContext | None, sqla_session: SQLAChatSession):
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
            await enqueue_job(ctx, job_id, job_type=WorkerFunction.CHAT_JOB)

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
        ctx: ViewContext | None,
        sqla_session: SQLAChatSession,
        messages: list[DocentChatMessage],
    ) -> tuple[list[DocentChatMessage], LLMContext]:
        """Get chat context including system prompt, context messages, and related objects.

        Returns either (messages, AgentRun) for single-run sessions or (messages, LLMContext) for multi-object sessions.
        """
        # Multi-object session with LLMContext
        if sqla_session.context_serialized is not None:
            spec = LLMContextSpec.model_validate(sqla_session.context_serialized)
            context = await load_context_objects(spec, self.mono_svc)
            system_prompt = context.get_system_message()
            context_messages = [
                SystemMessage(content=system_prompt),
                UserMessage(content=context.to_str()),
            ] + messages
            return context_messages, context

        # Single-run session
        if sqla_session.agent_run_id is None:
            raise ValueError(f"Session {sqla_session.id} has neither agent run nor context")

        # Context is required for single-run sessions
        if ctx is None:
            raise ValueError("ViewContext is required for single-run chat sessions")

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

        context = LLMContext(items=[agent_run])

        return context_messages, context

    async def one_turn(
        self,
        ctx: ViewContext | None,
        sqla_session: SQLAChatSession,
        sse_callback: ChatEventCallback | None = None,
    ):
        """Run one turn of the chat assistant. Called by worker process, not API server.
        Executes tool calls (e.g., add_label) and streams intermediate state.
        """

        raw_chat_session = sqla_session.to_pydantic()

        context_messages, context = await self._get_chat_context(
            ctx, sqla_session, raw_chat_session.messages
        )

        # Local working copy of raw messages (persisted form)
        raw_messages = raw_chat_session.messages.copy()

        async def _llm_streaming_callback(batch_index: int, llm_output: LLMOutput):
            if sse_callback and (completion := llm_output.first):
                if not completion.text:
                    return

                # Parse citations and suggestions for streaming display
                content_text = completion.text or ""
                cleaned_text_suggestions, suggestions = parse_suggestions(
                    content_text, streaming=True
                )
                cleaned_text, citations = resolve_citations_with_context(
                    cleaned_text_suggestions, context
                )

                assistant_msg = DocentAssistantMessage(
                    content=cleaned_text,
                    tool_calls=completion.tool_calls,
                    citations=citations,
                    suggested_messages=suggestions if suggestions else None,
                )

                # For existing single-run chats, parse citations in prior messages for consistent display
                # For "chat with anything", citations are already parsed in raw_messages
                if sqla_session.context_serialized is None:
                    prior_messages = _parse_citations_in_messages(raw_messages, context)
                else:
                    prior_messages = raw_messages

                all_messages = prior_messages + [assistant_msg]

                await sse_callback(raw_chat_session.model_copy(update={"messages": all_messages}))

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

            # 1) If the last message is an assistant message with no tool calls, break
            if last_message.role == "assistant" and not getattr(last_message, "tool_calls", None):
                break

            # 2) If user or tool: generate assistant continuation
            if last_message.role in ("user", "tool"):
                # Recompute context with the latest messages to avoid repeating tool calls
                context_messages, _ = await self._get_chat_context(ctx, sqla_session, raw_messages)

                outputs = await self.llm_svc.get_completions(
                    inputs=[context_messages],
                    model_options=[session_model],
                    max_new_tokens=8192,
                    timeout=120.0,
                    use_cache=True,
                    streaming_callback=_llm_streaming_callback,
                )
                result = outputs[0]

                # Handle provider errors first by surfacing an error state via sse_callback
                if result.did_error:
                    # TODO: if we hit rate limits after receiving a message, maybe we should still save the message
                    error_state = raw_chat_session.model_copy(
                        update={
                            "error_id": result.errors[0].error_type_id,
                            "error_message": result.errors[0].user_message,
                        }
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

                content_text = completion.text or ""
                cleaned_text, suggestions = parse_suggestions(content_text, streaming=False)

                cleaned_text, citations = resolve_citations_with_context(cleaned_text, context)
                assistant_msg = DocentAssistantMessage(
                    content=cleaned_text,
                    tool_calls=completion.tool_calls,
                    citations=citations,
                    suggested_messages=suggestions if suggestions else None,
                )
                raw_messages.append(assistant_msg)

                # Store real token count from API response if available
                total_tokens = result.usage.total_tokens
                if total_tokens > 0:
                    sqla_session.estimated_input_tokens = total_tokens

                    # For multi-run sessions, compute estimated_messages_tokens
                    # This anchors future estimates when visibility changes.
                    # base = ground_truth - context_estimate_at_call_time
                    if sqla_session.context_serialized is not None:
                        try:
                            item_estimates = compute_context_token_estimates(context)
                            visible_context_tokens = sum(
                                item_estimates.get(alias, 0)
                                for alias in context.root_items
                                if context.item_visibility.get(alias, True)
                            )
                            sqla_session.estimated_messages_tokens = (
                                total_tokens - visible_context_tokens
                            )
                        except Exception as e:
                            logger.warning(f"Failed to compute estimated_messages_tokens: {e}")

            # 3) If the last message is an assistant message with tool calls, execute the tool calls
            elif isinstance(last_message, DocentAssistantMessage) and last_message.tool_calls:
                # Removing the agent writing labels feature for now
                pass

            # Update session and notify
            await self._update_session(sqla_session, [m.model_dump() for m in raw_messages])
            await self.session.commit()

            # Push current state
            # For "chat with anything", citations are already parsed in raw_messages
            # For existing chats, we need to parse them for display
            if sse_callback:
                if sqla_session.context_serialized is not None:
                    # "Chat with anything": citations already parsed
                    messages_to_send = raw_messages
                else:
                    # Existing single-run chats: parse citations for display
                    messages_to_send = _parse_citations_in_messages(raw_messages, context)

                await sse_callback(
                    raw_chat_session.model_copy(update={"messages": messages_to_send})
                )

        # Final state
        # For "chat with anything", citations are already parsed and stored
        # For existing chats, parse them for the return value
        if sqla_session.context_serialized is not None:
            final_messages = raw_messages
        else:
            final_messages = _parse_citations_in_messages(raw_messages, context)

        return raw_chat_session.model_copy(update={"messages": final_messages})


async def cleanup_old_chat_sessions(session: AsyncSession, days_old: int = 7) -> int:
    """
    Delete chat sessions that haven't been updated in the specified number of days.
    This exists outside ChatService to avoid setting up RubricService and LLMService.

    Args:
        days_old: Number of days after which sessions are considered old (default: 7)

    Returns:
        Number of sessions deleted
    """
    cutoff_date = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days_old)

    result = await session.execute(
        delete(SQLAChatSession).where(
            SQLAChatSession.updated_at < cutoff_date, SQLAChatSession.context_serialized.is_(None)
        )
    )
    # Ensure the deletion is persisted
    await session.commit()
    deleted_count = result.rowcount or 0
    return deleted_count
