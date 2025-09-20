import json
import traceback
from datetime import UTC, datetime
from typing import AsyncContextManager, AsyncIterator, Callable, Literal, Protocol, cast
from uuid import uuid4

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from docent._log_util import get_logger
from docent.data_models.chat.message import (
    AssistantMessage,
    ChatMessage,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES
from docent_core._server._broker.redis_client import (
    STATE_KEY_FORMAT,
    STREAM_KEY_FORMAT,
    enqueue_job,
    get_redis_client,
)
from docent_core._worker.constants import WorkerFunction
from docent_core.docent.ai_tools.rubric.refine import (
    DIRECT_SEARCH_SYS_PROMPT,
    DIRECT_SEARCH_WELCOME_MESSAGE,
    FIRST_USER_MESSAGE_TEMPLATE,
    GUIDED_SEARCH_SYS_PROMPT,
    GUIDED_SEARCH_WELCOME_MESSAGE,
    RUN_SUMMARY_TEMPLATE,
    SummaryStreamingCallback,
    create_set_rubric_and_schema_tool,
    execute_set_rubric,
    summarize_agent_runs,
    update_user_message_with_labels,
)
from docent_core.docent.db.contexts import ViewContext
from docent_core.docent.db.schemas.refinement import (
    RefinementAgentSession,
    SQLARefinementAgentSession,
)
from docent_core.docent.db.schemas.tables import JobStatus, SQLAJob
from docent_core.docent.services.monoservice import MonoService
from docent_core.docent.services.rubric import RubricService, SQLARubric

logger = get_logger(__name__)


OPENERS = {"{": "}", "[": "]"}
CLOSERS = OPENERS.values()


def _optimistic_close_json(partial: str) -> str | None:
    """
    Returns a closed JSON string if the result is valid JSON,
    otherwise returns None.
    """
    s = partial
    stack: list[str] = []  # expected closers
    in_string = False
    escape = False

    # Track structural state
    for ch in s:
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in OPENERS:
                stack.append(OPENERS[ch])
            elif ch in CLOSERS and stack and ch == stack[-1]:
                stack.pop()

    buf = s

    # Close dangling string
    if in_string and not escape:
        buf += '"'

    def last_sig(text: str) -> str:
        for c in reversed(text):
            if not c.isspace():
                return c
        return ""

    ls = last_sig(buf)

    if ls == ":":
        buf += " null"
    elif ls == ",":
        buf += " null"

    # Close unmatched braces/brackets
    if stack:
        buf += "".join(reversed(stack))

    # Validate
    try:
        json.loads(buf)
        return buf
    except Exception:
        return None


class RefineAgentEventCallback(Protocol):
    async def __call__(self, session: RefinementAgentSession):
        pass


class RefinementService:
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

    async def get_session_by_id(self, session_id: str):
        result = await self.session.execute(
            select(SQLARefinementAgentSession).where(
                SQLARefinementAgentSession.id == session_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_session_by_rubric(self, sq_rubric: SQLARubric):
        result = await self.session.execute(
            select(SQLARefinementAgentSession).where(
                SQLARefinementAgentSession.rubric_id == sq_rubric.id,
            )
        )
        return result.scalar_one_or_none()

    async def get_or_create_session(
        self, sq_rubric: SQLARubric, session_type: Literal["guided", "direct"] = "guided"
    ):
        """Get or create a refinement session for a rubric.
        Uses an advisory lock to avoid races where multiple sessions are created per rubric.
        """

        async with self.mono_svc.advisory_lock(
            sq_rubric.collection_id, f"create_refinement_session_{sq_rubric.id}"
        ):
            sq_rsession = await self.get_session_by_rubric(sq_rubric)
            if sq_rsession is None:

                system_prompt = (
                    DIRECT_SEARCH_SYS_PROMPT
                    if session_type == "direct"
                    else GUIDED_SEARCH_SYS_PROMPT
                )

                # Ensure required fields are initialized so the instance is usable pre-flush
                rsession = RefinementAgentSession(
                    id=str(uuid4()),
                    rubric_id=sq_rubric.id,
                    rubric_version=sq_rubric.version,
                    messages=[SystemMessage(content=system_prompt)],
                    n_summaries=0,
                )
                sq_rsession = SQLARefinementAgentSession.from_pydantic(rsession)
                self.session.add(sq_rsession)
            return sq_rsession

    async def _update_session_messages(
        self, sq_rsession: SQLARefinementAgentSession, messages: list[ChatMessage]
    ):
        sq_rsession.content["messages"] = [m.model_dump() for m in messages]
        sq_rsession.updated_at = datetime.now(UTC).replace(tzinfo=None)
        flag_modified(sq_rsession, "content")  # Required to trigger a DB update

    async def _update_session_summaries(
        self, sq_rsession: SQLARefinementAgentSession, n_summaries: int | None
    ):
        sq_rsession.content["n_summaries"] = n_summaries
        sq_rsession.updated_at = datetime.now(UTC).replace(tzinfo=None)
        flag_modified(sq_rsession, "content")  # Required to trigger a DB update

    async def add_user_message(self, sq_rsession: SQLARefinementAgentSession, message: str):
        await self._update_session_messages(
            sq_rsession, sq_rsession.to_pydantic().messages + [UserMessage(content=message)]
        )

    async def get_current_state(
        self, sq_rsession: SQLARefinementAgentSession
    ) -> RefinementAgentSession:
        """Return the current state of the refinement session as a pydantic model."""
        return sq_rsession.to_pydantic()

    async def _get_agent_run_summaries(
        self, sq_rubric: SQLARubric, ctx: ViewContext, completion_callback: SummaryStreamingCallback
    ) -> str:
        """Summarize max 10 agent runs as initial context for the refinement agent."""

        # Get 10 random agent runs
        agent_runs = await self.mono_svc.get_agent_runs(ctx)

        N_SAMPLE_AGENT_RUNS = 10
        if len(agent_runs) > N_SAMPLE_AGENT_RUNS:
            import random

            random.seed(0)
            agent_runs = random.sample(agent_runs, N_SAMPLE_AGENT_RUNS)

        # Get summaries for max 10 agent runs
        outputs = await summarize_agent_runs(
            sq_rubric.rubric_text,
            agent_runs,
            completion_callback,
        )

        summary_body = ""
        for ar, output in zip(agent_runs, outputs):
            summary = output.first_text or ""
            summary_body += RUN_SUMMARY_TEMPLATE.format(agent_run_id=ar.id, summary=summary) + "\n"
        return "<summaries>\n" + summary_body + "\n</summaries>"

    @staticmethod
    async def _get_active_refinement_job(session: AsyncSession, session_id: str) -> SQLAJob | None:
        result = await session.execute(
            select(SQLAJob)
            .where(SQLAJob.type == WorkerFunction.REFINEMENT_AGENT_JOB.value)
            .where(SQLAJob.job_json["rsession_id"].astext == session_id)
            .where((SQLAJob.status == JobStatus.PENDING) | (SQLAJob.status == JobStatus.RUNNING))
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_job_for_session(self, session_id: str) -> SQLAJob | None:
        return await self._get_active_refinement_job(self.session, session_id)

    async def start_or_get_agent_job(
        self,
        ctx: ViewContext,
        sq_rsession: SQLARefinementAgentSession,
        show_labels_in_context: bool = False,
    ):
        """This job is responsible for running the refine agent for one turn.
        Uses an advisory lock to avoid races where multiple jobs are started for the same session.
        """

        async with self.mono_svc.advisory_lock(
            # FIXME(mengk): this is not the collection ID
            sq_rsession.id,
            f"start_refinement_session_{sq_rsession.id}",
        ):
            # Is there already a job for this session?
            existing_job = await self._get_active_refinement_job(self.session, sq_rsession.id)
            if existing_job:
                return existing_job.id

            # There is no running job, create a new one
            job_id = str(uuid4())
            self.session.add(
                SQLAJob(
                    id=job_id,
                    type=WorkerFunction.REFINEMENT_AGENT_JOB.value,
                    job_json={
                        "rsession_id": sq_rsession.id,
                        "show_labels_in_context": show_labels_in_context,
                    },
                )
            )

            # Exception to rule of not committing inside the service:
            #   commit so that the enqueued job is visible to the worker
            await self.session.commit()
            await enqueue_job(ctx, job_id)

            return job_id

    async def listen_for_job_state(self, job_id: str) -> AsyncIterator[RefinementAgentSession]:
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
                return RefinementAgentSession.model_validate_json(raw_state)
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

    async def refine_agent_one_turn(
        self,
        ctx: ViewContext,
        sq_rsession: SQLARefinementAgentSession,
        show_labels_in_context: bool,
        sse_callback: RefineAgentEventCallback | None = None,
    ):
        """Run one turn of the refinement agent.
        MAX_ITERS_PER_TURN is a safety limit to avoid infinite loops.
        Note: self.session is committed after each iteration of this turn.
        """

        # Get latest rubric
        # FIXME(mengk): reconcile this with the outdated foreign key
        sq_rubric = await self.rubric_svc.get_rubric(sq_rsession.rubric_id, version=None)
        if sq_rubric is None:
            raise ValueError(f"Rubric {sq_rsession.rubric_id} not found")

        rsession = sq_rsession.to_pydantic()
        lock = anyio.Lock()

        # Add labels to the user message if toggled on the FE
        last_message = rsession.messages[-1]
        if (
            show_labels_in_context
            and last_message.role == "user"
            # Don't add labels if they already exist on the user message
            and "labeled_results" not in last_message.content
        ):
            labels_and_results = await self.rubric_svc.get_judge_run_labels_and_results(
                sq_rsession.rubric_id
            )
            update_user_message_with_labels(rsession.messages, labels_and_results)
            # Update the user message immediately so labels persist on retry
            await self._update_session_messages(sq_rsession, rsession.messages)

        async def _summary_callback(batch_index: int, summary: str):
            """This stores summaries in the session state."""
            if sse_callback and summary:
                async with lock:
                    if rsession.n_summaries is None:
                        rsession.n_summaries = 0
                    rsession.n_summaries += 1
                    await sse_callback(rsession.prepare_for_client())

        async def _llm_callback(batch_index: int, llm_output: LLMOutput):
            """This *does NOT* store messages in the session state.
            The message is added at the end to avoid polluting the history with a bunch of partials.
            """
            if sse_callback and (completion := llm_output.first):
                for tool_call in completion.tool_calls or []:
                    # Try to optimistically close the arguments for streaming
                    raw_args = tool_call.arguments.get("__parse_error_raw_args")
                    if raw_args is not None:
                        if parsed_args := _optimistic_close_json(raw_args):
                            tool_call.arguments = json.loads(parsed_args)

                async with lock:
                    await sse_callback(
                        rsession.model_copy(
                            update={
                                "messages": rsession.messages
                                + [
                                    AssistantMessage(
                                        content=completion.text or "",
                                        tool_calls=completion.tool_calls,
                                    )
                                ]
                            }
                        ).prepare_for_client()
                    )

        logger.info(f"Running one turn of refinement session: {sq_rsession}")

        MAX_ITERS_PER_TURN = 5

        # Loop while last message is:
        # 1. Unhandled system/user: need to generate asst response
        # 2. Assistant message with tool calls: need to execute tool calls
        # 3. Tool call messages: need to have the agent decide what to do next given the responses
        # In other words, skip when the last message is an assistant message with no tool calls
        for _ in range(MAX_ITERS_PER_TURN):
            assert len(rsession.messages) > 0, "this should never fail"

            # Now handle the message sequence based on the last message
            last_message = rsession.messages[-1]

            # If the last message is an assistant message with no tool calls, break
            if last_message.role == "assistant" and not last_message.tool_calls:
                break

            # If system: generate the first user message with sample data
            if last_message.role == "system":
                is_guided = GUIDED_SEARCH_SYS_PROMPT == last_message.content

                # Add a welcome message and notify sse_callback
                welcome_message = (
                    GUIDED_SEARCH_WELCOME_MESSAGE if is_guided else DIRECT_SEARCH_WELCOME_MESSAGE
                )
                rsession.messages.append(AssistantMessage(content=welcome_message))
                if sse_callback:
                    await sse_callback(rsession.prepare_for_client())

                # Build the initial user message template
                message_content = FIRST_USER_MESSAGE_TEMPLATE.format(
                    rubric=sq_rubric.rubric_text,
                    output_schema=json.dumps(sq_rubric.output_schema, indent=2),
                )
                if is_guided:
                    # Get summaries for agent runs
                    message_content += await self._get_agent_run_summaries(
                        sq_rubric, ctx, _summary_callback
                    )

                # Append as a new user message
                rsession.messages.append(UserMessage(content=message_content))

                # Notify sse_callback
                if sse_callback:
                    await sse_callback(rsession.prepare_for_client())

            # If user or tool: generate asst continuation
            if last_message.role == "user" or last_message.role == "tool":

                messages = rsession.messages
                if last_message.role == "user":
                    user_message = UserMessage(content=last_message.content)
                    messages = messages[:-1] + [user_message]

                outputs = await get_llm_completions_async(
                    [messages],
                    PROVIDER_PREFERENCES.refine_agent,
                    tools=[
                        create_set_rubric_and_schema_tool(),
                    ],
                    tool_choice="auto",
                    max_new_tokens=8192,
                    timeout=180.0,
                    use_cache=True,
                    streaming_callback=_llm_callback,
                )

                result = outputs[0]

                if result.did_error:
                    error_state = rsession.prepare_for_client(result.errors[0].user_message)
                    if sse_callback:
                        await sse_callback(error_state)
                    return error_state

                # Parse completion and append to messages
                if (completion := result.first) is None:
                    continue
                assistant_msg = AssistantMessage(
                    content=completion.text or "", tool_calls=completion.tool_calls
                )
                rsession.messages.append(assistant_msg)

            # If assistant with tool calls: execute tool calls
            elif last_message.role == "assistant" and (tool_calls := last_message.tool_calls):
                for tc in tool_calls:
                    try:
                        if tc.function == "set_rubric_and_schema":
                            # Load current rubric
                            current_sq_rubric = await self.rubric_svc.get_rubric(
                                sq_rsession.rubric_id, version=None
                            )
                            if current_sq_rubric is None:
                                raise ValueError(
                                    f"Rubric {sq_rsession.rubric_id} not found during tool execution"
                                )

                            # Apply tool update and message
                            updated_rubric = current_sq_rubric.to_pydantic().model_copy(deep=True)
                            tool_result_msg = execute_set_rubric(updated_rubric, tc)
                            rsession.messages.append(tool_result_msg)

                            # If the output schema is invalid, don't persist the new version
                            if not isinstance(tool_result_msg.error, dict):
                                # Cancel existing eval rubric job
                                await self.rubric_svc.cancel_active_rubric_eval_job(
                                    current_sq_rubric.id
                                )

                                # Persist new rubric as a new version
                                await self.rubric_svc.add_rubric_version(
                                    updated_rubric.id, updated_rubric
                                )
                                # Point session's rubric_version pointer to the new version
                                rsession.rubric_version = updated_rubric.version

                                logger.error(f"Adding new rubric version: {updated_rubric.version}")

                                await self.rubric_svc.start_or_get_eval_rubric_job(
                                    ctx,
                                    updated_rubric.id,
                                )
                        else:
                            raise ValueError(f"Unsupported tool call: {tc.function}")
                    except Exception as e:
                        rsession.messages.append(
                            ToolMessage(
                                content=f"Error executing tool call: {e}",
                                error={"detail": str(e)},
                                function=tc.function,
                                tool_call_id=tc.id,
                            )
                        )

            # Update session
            await self._update_session_messages(sq_rsession, rsession.messages)
            await self._update_session_summaries(sq_rsession, rsession.n_summaries)

            # Commit before the callback so the FE will fetch the correct state
            await self.session.commit()

            if sse_callback:
                await sse_callback(sq_rsession.to_pydantic().prepare_for_client())

        return sq_rsession.to_pydantic().prepare_for_client()
