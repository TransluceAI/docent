"""Simple rollout experiment implementation."""

import asyncio
import json
import os
import traceback
from datetime import datetime
from typing import Any, AsyncIterator, Optional

import anyio
from openai import (
    AsyncOpenAI,
    BadRequestError,
    ContentFilterFinishReasonError,
    UnprocessableEntityError,
)
from pydantic import BaseModel

from docent._log_util import get_logger
from docent.data_models import AgentRun, Transcript
from docent.data_models.chat import (
    AssistantMessage,
    ChatMessage,
    ContentReasoning,
    ContentText,
    SystemMessage,
    ToolMessage,
    UserMessage,
)
from docent.data_models.chat.tool import ToolCall
from docent_core.investigator.tools.backends.anthropic_compatible_backend import (
    AnthropicCompatibleBackendConfig,
)
from docent_core.investigator.tools.backends.anthropic_compatible_backend import (
    ModelWithClient as AnthropicCompatibleModelWithClient,
)
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    ModelWithClient as OpenAICompatibleModelWithClient,
)
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
)
from docent_core.investigator.tools.common.types import (
    ExperimentStatus,
    GradeEnd,
    MessageEnd,
    MessageStart,
    RolloutEnd,
    RolloutErrorEvent,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    generate_uid,
)
from docent_core.investigator.tools.policies.deterministic import (
    DeterministicContextPolicyConfig,
)
from docent_core.investigator.tools.rollout.interaction_stream import (
    StreamEvent,
    generate_interaction_stream,
)
from docent_core.investigator.tools.simple_rollout.types import (
    SimpleRolloutAgentRunMetadata,
    SimpleRolloutExperimentConfig,
    SimpleRolloutExperimentResult,
)
from docent_core.investigator.tools.subject_models.anthropic_compatible_subject_model import (
    AnthropicCompatibleSubjectModel,
)
from docent_core.investigator.tools.subject_models.openai_compatible_subject_model import (
    OpenAICompatibleSubjectModel,
)
from docent_core.investigator.utils.async_util.concurrency_limiters import (
    LimiterRegistry,
    rate_limiting,
)

logger = get_logger(__name__)


class RolloutState(BaseModel):
    """Track state for building messages during rollout streaming."""

    transcript: Transcript
    metadata: SimpleRolloutAgentRunMetadata
    messages_by_id: dict[str, ChatMessage] = {}
    # Track Content blocks for assistant messages (always use Content list format)
    reasoning_blocks: dict[str, ContentReasoning] = {}
    text_blocks: dict[str, ContentText] = {}
    tool_calls_by_message: dict[str, dict[int, dict[str, Any]]] = (
        {}
    )  # message_id -> index -> tool call data

    class Config:
        arbitrary_types_allowed = True


class SimpleRolloutExperiment:
    """Run simple rollout experiments."""

    def __init__(self, config: SimpleRolloutExperimentConfig):
        self.config = config
        self.result = SimpleRolloutExperimentResult(
            config=config,
            experiment_status=ExperimentStatus(
                status="running",
                progress=0.0,
                start_time=datetime.now(),
            ),
            base_policy_config=self.config.base_context.to_deterministic_context_policy_config(),
        )

        # Build (model_with_client, subject_model_class) tuples for each backend
        self.subject_models_info: list[
            tuple[OpenAICompatibleModelWithClient | AnthropicCompatibleModelWithClient, type]
        ] = []
        for backend in self.config.backends:
            model_with_client = backend.build_client()
            if isinstance(backend, OpenAICompatibleBackendConfig):
                subject_model_class = OpenAICompatibleSubjectModel
            elif isinstance(backend, AnthropicCompatibleBackendConfig):  # type: ignore
                subject_model_class = AnthropicCompatibleSubjectModel
            else:
                raise ValueError(f"Unknown backend type: {type(backend)}")
            self.subject_models_info.append((model_with_client, subject_model_class))

        # Build judge client if needed (only if judge is configured)
        self.anthropic_client = None
        self.anthropic_limiter = None
        if self.config.judge_config:
            # These clients should ideally be managed globally
            assert os.getenv("ANTHROPIC_API_KEY") is not None, "ANTHROPIC_API_KEY is not set"

            self.anthropic_client = AsyncOpenAI(
                api_key=os.getenv("ANTHROPIC_API_KEY"),
                base_url="https://api.anthropic.com/v1/",
            )
            self.anthropic_limiter = LimiterRegistry("anthropic")

    async def run(self) -> AsyncIterator[SimpleRolloutExperimentResult]:
        """
        Run the simple rollout experiment.

        This runs the specified number of replicas for each backend with the base context,
        optionally grading each run.

        Yields the result after each update for streaming.
        """
        # Configure limiters if judge is configured
        if self.anthropic_limiter:
            await self.anthropic_limiter.configure(rate_limiting(rpm=10_000, max_in_flight=128))

        # Validate experiment configuration limits
        if self.config.num_replicas > 256:
            error_message = (
                f"Number of replicas ({self.config.num_replicas}) exceeds maximum of 256"
            )
            logger.error(error_message)
            self.result.experiment_status.status = "error"
            self.result.experiment_status.error_message = error_message
            yield self.result
            return

        # Total rollouts is replicas × backends
        total_rollouts = self.config.num_replicas * len(self.config.backends)
        if total_rollouts > 1024:
            error_message = (
                f"Experiment configuration exceeds limits: "
                f"{self.config.num_replicas} replicas × "
                f"{len(self.config.backends)} backends = {total_rollouts} rollouts. "
                f"Maximum allowed is 1024 total rollouts."
            )
            logger.error(error_message)
            self.result.experiment_status.status = "error"
            self.result.experiment_status.error_message = error_message
            yield self.result
            return

        # Initialize result structures
        self.result.agent_runs = {}
        self.result.agent_run_metadata = {}
        # Queue to collect streaming events from all rollouts
        event_queue: asyncio.Queue[tuple[str, StreamEvent]] = asyncio.Queue()

        # Track completion per rollout (includes grading)
        completed_runs: set[str] = set()

        def mark_run_completed(agent_run_id: str) -> None:
            if agent_run_id in completed_runs:
                return

            completed_runs.add(agent_run_id)
            if total_rollouts > 0:
                self.result.experiment_status.progress = (
                    len(completed_runs) / total_rollouts * 100.0
                )

        # Store rollout state for message building
        rollout_states: dict[str, RolloutState] = {}

        async def run_single_rollout(
            agent_run_id: str,
            replica_idx: int,
            backend_name: str,
            model_with_client: OpenAICompatibleModelWithClient | AnthropicCompatibleModelWithClient,
            subject_model_class: type,
            policy_config: DeterministicContextPolicyConfig,
        ):
            """Run a single rollout and stream events to the queue."""
            try:
                # Build the policy and subject model for this rollout
                policy = policy_config.build()
                subject_model = subject_model_class(
                    model_with_client,
                    policy_config.tools,
                )

                # Build judge if configured
                judge = None
                if self.config.judge_config and self.anthropic_client and self.anthropic_limiter:
                    judge = self.config.judge_config.build(
                        client=self.anthropic_client,
                        limiter=self.anthropic_limiter,
                    )

                # Stream the interaction
                async for event in generate_interaction_stream(
                    policy=policy,
                    subject_model=subject_model,
                    grader=judge,
                ):
                    await event_queue.put((agent_run_id, event))

            except Exception as e:
                logger.warning(f"Rollout failed: {e}\n{traceback.format_exc()}")

                # Determine user-safe error message
                user_error_message: Optional[str] = None
                if isinstance(
                    e, (BadRequestError, UnprocessableEntityError, ContentFilterFinishReasonError)
                ):
                    user_error_message = str(e)

                error_event = RolloutErrorEvent(error=e, user_error_message=user_error_message)
                await event_queue.put((agent_run_id, error_event))

        # Start all rollouts concurrently (all backends × all replicas)
        async with anyio.create_task_group() as tg:
            for backend_config, (model_with_client, subject_model_class) in zip(
                self.config.backends, self.subject_models_info
            ):
                for replica_idx in range(self.config.num_replicas):
                    # Generate unique IDs for this rollout
                    agent_run_id = generate_uid()
                    transcript_id = generate_uid()

                    # Create metadata for this rollout
                    metadata = SimpleRolloutAgentRunMetadata(
                        model=model_with_client.model,
                        backend_name=backend_config.name,
                        replica_idx=replica_idx,
                    )
                    self.result.agent_run_metadata[agent_run_id] = metadata

                    # Create the transcript (initially empty)
                    transcript_metadata = {}
                    if self.result.base_policy_config and self.result.base_policy_config.tools:
                        # Store tools in transcript metadata for frontend display
                        transcript_metadata["tools"] = [
                            tool.model_dump() for tool in self.result.base_policy_config.tools
                        ]

                    transcript = Transcript(
                        id=transcript_id,
                        messages=[],
                        metadata=transcript_metadata,
                    )

                    # Create the agent run with backend name in metadata
                    agent_run = AgentRun(
                        id=agent_run_id,
                        name=f"{backend_config.name} - Replica {replica_idx + 1}",
                        description=f"Simple rollout with {backend_config.name}, replica {replica_idx + 1}",
                        transcripts=[transcript],
                        metadata={
                            **metadata.model_dump(),
                            "backend_name": backend_config.name,
                        },
                    )

                    # Store the agent run immediately
                    self.result.agent_runs[agent_run_id] = agent_run

                    # Initialize rollout state for message building
                    rollout_states[agent_run_id] = RolloutState(
                        transcript=transcript,
                        metadata=metadata,
                    )

                    # Start the rollout task
                    if self.result.base_policy_config:
                        tg.start_soon(
                            run_single_rollout,
                            agent_run_id,
                            replica_idx,
                            backend_config.name,
                            model_with_client,
                            subject_model_class,
                            self.result.base_policy_config,
                        )

            # Process events from all rollouts until they complete
            while len(completed_runs) < total_rollouts:
                try:
                    # Get the next event with timeout
                    agent_run_id, event = await asyncio.wait_for(
                        event_queue.get(), timeout=60.0  # 60 second timeout
                    )
                except asyncio.TimeoutError:
                    logger.error("Timeout waiting for rollout events")
                    break

                # Get the rollout state
                state = rollout_states[agent_run_id]
                metadata = state.metadata

                # Process the event
                if isinstance(event, RolloutErrorEvent):
                    # Mark as errored
                    metadata.state = "errored"
                    metadata.error_message = event.user_error_message

                    # Determine error type
                    if isinstance(event.error, BadRequestError):
                        metadata.error_type = "subject_model_error"
                    elif isinstance(
                        event.error, (UnprocessableEntityError, ContentFilterFinishReasonError)
                    ):
                        metadata.error_type = "policy_error"
                    elif isinstance(event.error, TimeoutError):
                        metadata.error_type = "timeout_error"
                    elif isinstance(event.error, ConnectionError):
                        metadata.error_type = "network_error"
                    else:
                        metadata.error_type = "unknown_error"

                    mark_run_completed(agent_run_id)

                elif isinstance(event, MessageStart):
                    # Create a new message and add it to the transcript immediately
                    if event.role == "user":
                        msg = UserMessage(
                            id=event.message_id,
                            content="",  # Start with empty content
                        )
                    elif event.role == "assistant":
                        # Always use Content list format for assistant messages
                        reasoning_block = ContentReasoning(type="reasoning", reasoning="")
                        text_block = ContentText(type="text", text="")
                        state.reasoning_blocks[event.message_id] = reasoning_block
                        state.text_blocks[event.message_id] = text_block

                        msg = AssistantMessage(
                            id=event.message_id,
                            content=[
                                reasoning_block,
                                text_block,
                            ],  # Start with empty Content blocks
                        )
                    elif event.role == "tool":
                        msg = ToolMessage(
                            id=event.message_id,
                            content="",  # Start with empty content
                            tool_call_id=event.tool_call_id,  # Include the tool_call_id from the event
                        )
                    else:  # system
                        msg = SystemMessage(
                            id=event.message_id,
                            content="",  # Start with empty content
                        )

                    # Add the message to the transcript immediately
                    state.transcript.messages.append(msg)
                    state.messages_by_id[event.message_id] = msg

                elif isinstance(event, TokenDelta):
                    # Update Content blocks in real-time
                    if event.is_thinking:
                        # Append to reasoning block
                        reasoning_block = state.reasoning_blocks.get(event.message_id)
                        if reasoning_block:
                            reasoning_block.reasoning += event.content
                    else:
                        # Append to text block or string content
                        text_block = state.text_blocks.get(event.message_id)
                        if text_block:
                            text_block.text += event.content
                        else:
                            # For non-assistant messages (user, system, tool)
                            msg = state.messages_by_id.get(event.message_id)
                            if msg and isinstance(msg.content, str):
                                msg.content += event.content

                elif isinstance(event, ToolCallStart):
                    # Initialize tool call tracking for this message
                    if event.message_id not in state.tool_calls_by_message:
                        state.tool_calls_by_message[event.message_id] = {}

                    state.tool_calls_by_message[event.message_id][event.tool_call_index] = {
                        "id": event.tool_call_id,
                        "name": event.function_name,
                        "arguments": "",
                        "type": event.type,
                    }

                elif isinstance(event, ToolCallDelta):
                    if event.message_id in state.tool_calls_by_message:
                        if event.tool_call_index in state.tool_calls_by_message[event.message_id]:
                            state.tool_calls_by_message[event.message_id][event.tool_call_index][
                                "arguments"
                            ] += event.arguments_delta

                elif isinstance(event, ToolCallEnd):
                    # Tool call is complete, add it to the message
                    if event.message_id in state.tool_calls_by_message:
                        msg = state.messages_by_id.get(event.message_id)
                        if isinstance(msg, AssistantMessage):
                            # Build tool calls list
                            tool_calls: list[ToolCall] = []
                            for idx in sorted(state.tool_calls_by_message[event.message_id].keys()):
                                tc_data = state.tool_calls_by_message[event.message_id][idx]
                                # Parse arguments as JSON
                                try:
                                    args: dict[str, Any] = (
                                        json.loads(tc_data["arguments"])
                                        if tc_data["arguments"]
                                        else {}
                                    )
                                except (json.JSONDecodeError, TypeError):
                                    args = {}

                                tool_calls.append(
                                    ToolCall(
                                        id=tc_data["id"],
                                        function=tc_data["name"],
                                        arguments=args,
                                        type=(
                                            tc_data["type"]
                                            if tc_data["type"] == "function"
                                            else None
                                        ),
                                    )
                                )
                            msg.tool_calls = tool_calls if tool_calls else None

                elif isinstance(event, MessageEnd):
                    # Message is complete, nothing more to do (content already streamed)
                    pass

                elif isinstance(event, GradeEnd):
                    # Store the grade (just the float value in metadata)
                    metadata.grade = event.annotation.grade

                    metadata.state = "completed"

                    # Also store grade and grader response in agent run metadata if judge is configured
                    if self.config.judge_config:
                        agent_run = self.result.agent_runs[agent_run_id]
                        agent_run.metadata["grade"] = event.annotation.grade
                        agent_run.metadata["grader_output"] = event.annotation.grader_response

                    # If a judge is configured, mark as completed when grading is complete
                    mark_run_completed(agent_run_id)

                elif isinstance(event, RolloutEnd):
                    # Content blocks are already updated in real-time, no conversion needed
                    # Just mark as completed if not already errored
                    if metadata.state != "errored":
                        metadata.state = "completed"

                    if self.config.judge_config is None:
                        # If no judge is configured, mark as completed when rollout is complete
                        mark_run_completed(agent_run_id)

                yield self.result

        # Update final status
        self.result.experiment_status.progress = 100.0
        self.result.experiment_status.status = "completed"

        # Yield final result
        yield self.result
