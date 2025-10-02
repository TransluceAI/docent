"""
This module contains the logic for creating experiments that study targeted interventions to a
deterministic policy/prompt.

Flow for generating counterfactuals:
1. Start with an ExperimentIdea.
2. Generate a list of counterfactual ideas (gen_counterfactual_ideas)

    ExperimentIdea -> ParsedCounterfactualIdeas

3. Turn the ParsedCounterfactualIdeas into a DeterministicContextPolicyConfig's
    (apply_counterfactual_contexts)

    # counterfactual idea id -> DeterministicContextPolicyConfig
    ParsedCounterfactualIdeas -> dict[str, DeterministicContextPolicyConfig]

4. Roll out the DeterministicContextPolicyConfigs with the Backend and Judge to generate AgentRuns

Inspiration:

Platt, 1964. Strong Inference: Certain systematic methods of scientific thinking may produce much more rapid progress than others. https://pages.ucsd.edu/~jmoore/courses/anth42web/Platt1964.pdf

Strong inference consists of applying the following steps to every problem in science, formally and explicitly and regularly:
1) Devising alternative hypotheses;
2) Devising a crucial experiment (or several of them), with alternative possible outcomes, each of which will, as nearly as possible, exclude one or more of the hypotheses;
3) Carrying out the experiment so as to get a clean result;
4) Recycling the procedure, making subhypotheses or sequential hypotheses to refine the possibilities that remain;
and so on.

"""

import asyncio
import json
import os
import traceback
from datetime import datetime
from typing import Any, AsyncIterator, Literal, TypedDict

import anyio
from google import genai
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
from docent_core.investigator.tools.backends.openai_compatible_backend import (
    OpenAICompatibleBackendConfig,
)
from docent_core.investigator.tools.common.types import (
    ExperimentStatus,
    GradeEnd,
    GradeStart,
    GradeUpdate,
    MessageEnd,
    MessageStart,
)
from docent_core.investigator.tools.common.types import RolloutEnd as RolloutEndEvent
from docent_core.investigator.tools.common.types import (
    RolloutErrorEvent,
    StreamEvent,
    TokenDelta,
    ToolCallDelta,
    ToolCallEnd,
    ToolCallStart,
    generate_uid,
)
from docent_core.investigator.tools.contexts.base_context import BaseContext
from docent_core.investigator.tools.counterfactual_analysis.apply_counterfactual_contexts import (
    llm_apply_counterfactual_to_base_context,
)
from docent_core.investigator.tools.counterfactual_analysis.gen_counterfactual_ideas import (
    ParsedCounterfactualIdeas,
    llm_generate_counterfactual_ideas,
)
from docent_core.investigator.tools.counterfactual_analysis.types import (
    CounterfactualAgentRunMetadata,
    CounterfactualExperimentConfig,
    CounterfactualExperimentResult,
    CounterfactualIdea,
    DeterministicContextPolicyConfig,
)
from docent_core.investigator.tools.rollout.interaction_stream import generate_interaction_stream
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


class ToolCallTrackingData(TypedDict):
    """Data structure for tracking tool call information during streaming."""

    id: str
    name: str
    arguments: str
    type: str  # "function" or "custom"


class RolloutState(BaseModel):
    """State for tracking a single rollout's progress during execution."""

    transcript: Transcript
    metadata: CounterfactualAgentRunMetadata
    messages_by_id: dict[str, ChatMessage] = {}
    # Track Content blocks for assistant messages (always use Content list format)
    reasoning_blocks: dict[str, ContentReasoning] = {}
    text_blocks: dict[str, ContentText] = {}
    tool_calls_by_message: dict[str, dict[int, ToolCallTrackingData]] = (
        {}
    )  # message_id -> index -> tool call data

    class Config:
        arbitrary_types_allowed = True


class CounterfactualExperiment:
    def __init__(self, config: CounterfactualExperimentConfig):
        self.config = config
        self.result = CounterfactualExperimentResult(
            config=config,
            experiment_status=ExperimentStatus(
                status="running", progress=0.0, start_time=datetime.now()
            ),
            base_policy_config=self.config.base_context.to_deterministic_context_policy_config(),
        )

        # TODO(neil): these clients and limiters should be managed globally, not from
        # within the CounterfactualExperiment class.

        assert os.getenv("OPENAI_API_KEY") is not None, "OPENAI_API_KEY is not set"
        assert os.getenv("ANTHROPIC_API_KEY") is not None, "ANTHROPIC_API_KEY is not set"
        assert os.getenv("GOOGLE_API_KEY") is not None, "GOOGLE_API_KEY is not set"

        self.openai_client = AsyncOpenAI()
        self.anthropic_client = AsyncOpenAI(
            api_key=os.getenv("ANTHROPIC_API_KEY"), base_url="https://api.anthropic.com/v1/"
        )
        self.gemini_client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

        # Build the appropriate subject model based on backend type
        if isinstance(self.config.backend, OpenAICompatibleBackendConfig):
            self.subject_model_with_client = self.config.backend.build_client()
            self.subject_model_class = OpenAICompatibleSubjectModel
        elif isinstance(self.config.backend, AnthropicCompatibleBackendConfig):  # type: ignore
            self.subject_model_with_client = self.config.backend.build_client()
            self.subject_model_class = AnthropicCompatibleSubjectModel
        else:
            raise ValueError(f"Unknown backend type: {type(self.config.backend)}")

        self.openai_limiter = LimiterRegistry("openai")
        self.anthropic_limiter = LimiterRegistry("anthropic")
        self.gemini_limiter = LimiterRegistry("google")

    def _get_sanitized_error_info(self, exception: Exception) -> tuple[
        Literal[
            "policy_error",
            "subject_model_error",
            "judge_error",
            "network_error",
            "timeout_error",
            "unknown_error",
        ],
        str,
    ]:
        """
        Convert an exception to sanitized error type and message for frontend display.

        Returns:
            tuple of (error_type, error_message) where both are safe for frontend display
        """
        exception_type_name = type(exception).__name__.lower()
        exception_module = getattr(type(exception), "__module__", "").lower()

        if (
            "openai" in exception_module
            or "anthropic" in exception_module
            or "openai" in exception_type_name
            or "anthropic" in exception_type_name
        ):
            return "subject_model_error", "Subject model failed to generate response"
        elif "timeout" in exception_type_name:
            return "timeout_error", "Operation timed out"
        elif (
            "network" in exception_type_name
            or "connection" in exception_type_name
            or "requests" in exception_module
            or "urllib" in exception_module
        ):
            return "network_error", "Network connection failed"
        else:
            logger.error(f"Unknown error in rollout: {exception}", exc_info=True)
            return "unknown_error", "An unexpected error occurred"

    async def _create_errored_agent_run(
        self,
        agent_run_id: str,
        transcript_id: str,
        cf_idea_or_base_context: CounterfactualIdea | BaseContext,
        replica_idx: int,
        subject_model: str,
        exception: Exception,
        user_error_message: str | None = None,
    ) -> tuple[AgentRun, CounterfactualAgentRunMetadata]:
        """
        Create an agent run and metadata for a failed rollout.
        """
        error_type, sanitized_error_message = self._get_sanitized_error_info(exception)
        display_error_message = user_error_message or sanitized_error_message

        # Create metadata with error information
        metadata = CounterfactualAgentRunMetadata(
            model=subject_model,
            counterfactual_id=cf_idea_or_base_context.id,
            counterfactual_name=cf_idea_or_base_context.name,
            counterfactual_description=(
                cf_idea_or_base_context.description
                if isinstance(cf_idea_or_base_context, CounterfactualIdea)
                else "Base context"
            ),
            replica_idx=replica_idx,
            state="errored",
            error_type=error_type,
            error_message=display_error_message,
        )

        transcript = Transcript(
            id=transcript_id,
            messages=[],
        )

        # Create agent run
        agent_run = AgentRun(
            id=agent_run_id,
            name=f"{cf_idea_or_base_context.name} - Replica {replica_idx + 1} (Error)",
            description=f"Failed rollout: {display_error_message}",
            transcripts=[transcript],
            metadata=metadata.model_dump(),
        )

        return agent_run, metadata

    async def run(self) -> AsyncIterator[CounterfactualExperimentResult]:
        """
        Run the counterfactual experiment.
        """
        await self.configure_limiters()

        # Validate experiment configuration limits
        # Check individual limits first
        if self.config.num_counterfactuals > 64:
            error_message = (
                f"Number of counterfactuals ({self.config.num_counterfactuals}) "
                f"exceeds maximum of 64"
            )
            logger.error(error_message)
            self.result.experiment_status.status = "error"
            self.result.experiment_status.error_message = error_message
            yield self.result
            return

        if self.config.num_replicas > 256:
            error_message = (
                f"Number of replicas ({self.config.num_replicas}) " f"exceeds maximum of 256"
            )
            logger.error(error_message)
            self.result.experiment_status.status = "error"
            self.result.experiment_status.error_message = error_message
            yield self.result
            return

        # Total rollouts includes base context + counterfactuals, all multiplied by replicas
        total_rollouts = (self.config.num_counterfactuals + 1) * self.config.num_replicas
        if total_rollouts > 1024:
            error_message = (
                f"Experiment configuration exceeds limits: "
                f"({self.config.num_counterfactuals} + 1 base) × "
                f"{self.config.num_replicas} replicas = {total_rollouts} rollouts. "
                f"Maximum allowed is 1024 total rollouts."
            )
            logger.error(error_message)
            self.result.experiment_status.status = "error"
            self.result.experiment_status.error_message = error_message
            yield self.result
            return

        try:
            # Experiment-level phases - errors here should fail the entire experiment
            async for event in self.generate_counterfactual_ideas():
                yield event
            async for event in self.apply_counterfactual_contexts():
                yield event

            async for event in self.run_rollout():
                yield event

        except Exception as e:
            logger.error(f"Experiment failed: {e}\n{traceback.format_exc()}")
            _, error_message = self._get_sanitized_error_info(e)
            self.result.experiment_status.status = "error"
            self.result.experiment_status.error_message = error_message
            yield self.result

    async def configure_limiters(self) -> None:
        """
        Configure the limiters for the experiment.
        """
        await self.openai_limiter.configure(rate_limiting(rpm=10_000, max_in_flight=128))
        await self.anthropic_limiter.configure(rate_limiting(rpm=10_000, max_in_flight=128))
        await self.gemini_limiter.configure(rate_limiting(rpm=10_000, max_in_flight=128))

    async def generate_counterfactual_ideas(self) -> AsyncIterator[CounterfactualExperimentResult]:
        """
        Generate counterfactual ideas for the experiment, given the `idea`.

        Example:
        - idea: "Change the primary goal to something more realistic for a corporate AI agent, not serving American interests."
        - counterfactual idea: "Change the primary goal from 'serving American interests' to 'delivering maximum value to SummitBridge clients' in both instances where the original goal is mentioned."

        Yields:
        - CounterfactualExperimentResult with the counterfactual idea output and parsed counterfactual ideas. When finished, the parsed counterfactual ideas will be set.
        """

        self.result.counterfactual_idea_output = ""

        async for event in llm_generate_counterfactual_ideas(
            self.anthropic_client,
            self.config.base_context,
            self.config.idea,
            num_counterfactuals=self.config.num_counterfactuals,
            model="claude-sonnet-4-20250514",
        ):
            if isinstance(event, TokenDelta):
                self.result.counterfactual_idea_output += event.content
            if isinstance(event, ParsedCounterfactualIdeas):
                self.result.parsed_counterfactual_ideas = event
            yield self.result

    async def apply_counterfactual_contexts(self) -> AsyncIterator[CounterfactualExperimentResult]:
        """
        Apply counterfactuals to the base context, given the parsed counterfactual ideas.
        """

        assert (
            self.result.parsed_counterfactual_ideas is not None
        ), "Parsed counterfactual ideas not set. Did you call `generate_counterfactual_ideas` first?"

        self.result.counterfactual_context_output = {}
        self.result.counterfactual_policy_configs = {}

        # Run LLM applications for each counterfactual idea in parallel and stream updates.
        # Use a local limiter registry configured with no limiting by default.
        parsed = self.result.parsed_counterfactual_ideas
        assert parsed is not None

        # Queue to collect streaming events from each counterfactual application
        event_queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        # Track completion per counterfactual (we treat receipt of the final policy config as done)
        total_counterfactuals = len(parsed.counterfactuals)
        completed: set[str] = set()

        async def run_single(cf_id: str, idea: CounterfactualIdea):
            async for event in llm_apply_counterfactual_to_base_context(
                self.gemini_client,
                self.config.base_context,
                idea,
                limiter=self.gemini_limiter,
                model="gemini-2.5-flash-lite",
            ):
                await event_queue.put((cf_id, event))

        async with anyio.create_task_group() as tg:
            # Start all counterfactual applications
            for cf_id, idea in parsed.counterfactuals.items():
                # Initialize output buffer for this counterfactual
                self.result.counterfactual_context_output[cf_id] = ""
                tg.start_soon(run_single, cf_id, idea)

            # Process events until all counterfactuals complete
            while len(completed) < total_counterfactuals:
                cf_id, event = await event_queue.get()

                # Stream token updates into the appropriate buffer and yield incremental results
                if isinstance(event, MessageStart):
                    # Clear the output buffer when starting a new message (e.g., on retry)
                    self.result.counterfactual_context_output[cf_id] = ""
                elif isinstance(event, TokenDelta):
                    self.result.counterfactual_context_output[cf_id] += event.content
                elif isinstance(event, DeterministicContextPolicyConfig):
                    completed.add(cf_id)
                    self.result.counterfactual_policy_configs[cf_id] = event

                yield self.result

    async def run_rollout(self) -> AsyncIterator[CounterfactualExperimentResult]:
        """
        Run rollouts for all context policies (including the base context policy derived from the
        base context, as well as the counterfactual context policies).

        Uses the judge_config from the experiment config to build a judge for each rollout.
        Uses self.subject_model_with_client to generate the subject model responses, instantiating
        an OpenAICompatibleSubjectModel for each rollout.

        Stores the results in self.result.agent_runs. Also includes CounterfactualAgentRunMetadata
        for each rollout.

        Note: the id of the base policy is set to the id of the base context. All other ids
        follow the id of the counterfactual idea.

        """

        # Initialize result structures
        self.result.agent_runs = {}
        self.result.agent_run_metadata = {}

        # Prepare all policies to run (base + counterfactuals)
        all_policies: list[
            tuple[CounterfactualIdea | BaseContext, DeterministicContextPolicyConfig]
        ] = []

        # Add base policy
        if self.result.base_policy_config:
            all_policies.append(
                (
                    self.config.base_context,
                    self.result.base_policy_config,
                )
            )

        # Add counterfactual policies
        if self.result.counterfactual_policy_configs and self.result.parsed_counterfactual_ideas:
            for cf_id, policy_config in self.result.counterfactual_policy_configs.items():
                all_policies.append(
                    (self.result.parsed_counterfactual_ideas.counterfactuals[cf_id], policy_config)
                )

        # Track total rollouts for progress
        total_rollouts = len(all_policies) * self.config.num_replicas
        completed_rollouts_count = 0

        # Queue to collect streaming events from all rollouts
        event_queue: asyncio.Queue[tuple[str, StreamEvent]] = asyncio.Queue()

        # Track completion per rollout
        completed_rollouts: set[str] = set()

        # Store rollout state for message building
        rollout_states: dict[str, RolloutState] = {}

        async def run_single_rollout(
            agent_run_id: str,
            policy_config: DeterministicContextPolicyConfig,
        ):
            """Run a single rollout and stream events to the queue."""
            try:
                # Build the policy, subject model, and judge for this rollout
                policy = policy_config.build()
                subject_model = self.subject_model_class(
                    self.subject_model_with_client, policy_config.tools  # type: ignore
                )
                judge = self.config.judge_config.build(
                    client=self.anthropic_client, limiter=self.anthropic_limiter
                )

                # Stream the interaction
                async for event in generate_interaction_stream(
                    policy=policy,
                    subject_model=subject_model,
                    grader=judge,
                ):
                    await event_queue.put((agent_run_id, event))
            except Exception as e:
                # Note: we don't always want to log errors, because they can potentially leak
                # sensitive information. However, we have a whitelisted set of error types that
                # we can show the user.

                logger.warning(f"Rollout failed: {e}\n{traceback.format_exc()}")

                user_error_message: str | None = None
                if isinstance(
                    e, (BadRequestError, UnprocessableEntityError, ContentFilterFinishReasonError)
                ):
                    user_error_message = str(e)

                error_event = RolloutErrorEvent(error=e, user_error_message=user_error_message)
                await event_queue.put((agent_run_id, error_event))

        async with anyio.create_task_group() as tg:
            # Start all rollouts concurrently
            for cf_idea_or_base_context, policy_config in all_policies:
                for replica_idx in range(self.config.num_replicas):
                    # Generate unique IDs for this rollout
                    agent_run_id = generate_uid()
                    transcript_id = generate_uid()

                    # Create metadata for this rollout
                    metadata = CounterfactualAgentRunMetadata(
                        model=self.subject_model_with_client.model,
                        counterfactual_id=cf_idea_or_base_context.id,
                        counterfactual_name=cf_idea_or_base_context.name,
                        counterfactual_description=(
                            cf_idea_or_base_context.description
                            if isinstance(cf_idea_or_base_context, CounterfactualIdea)
                            else "Base context"
                        ),
                        replica_idx=replica_idx,
                    )
                    self.result.agent_run_metadata[agent_run_id] = metadata

                    # Create the transcript (initially empty)
                    # Add tools to transcript metadata if they exist
                    transcript_metadata = {}
                    if policy_config.tools:
                        # Store tools in transcript metadata for frontend display
                        transcript_metadata["tools"] = [
                            tool.model_dump() for tool in policy_config.tools
                        ]

                    transcript = Transcript(
                        id=transcript_id,
                        messages=[],  # Will be populated as events stream in
                        metadata=transcript_metadata,
                    )

                    # Create the agent run
                    agent_run = AgentRun(
                        id=agent_run_id,
                        name=f"{cf_idea_or_base_context.name} - Replica {replica_idx + 1}",
                        description=(
                            f"Counterfactual experiment rollout: {cf_idea_or_base_context.description}"
                            if isinstance(cf_idea_or_base_context, CounterfactualIdea)
                            else "Base context rollout"
                        ),
                        transcripts=[transcript],
                        metadata=metadata.model_dump(),
                    )

                    # Store the agent run immediately
                    self.result.agent_runs[agent_run_id] = agent_run

                    # Initialize rollout state for message building
                    rollout_states[agent_run_id] = RolloutState(
                        transcript=transcript,
                        metadata=metadata,
                        messages_by_id={},
                    )

                    # Start the rollout task
                    tg.start_soon(
                        run_single_rollout,
                        agent_run_id,
                        policy_config,
                    )

            # Process events from all rollouts until they complete
            while len(completed_rollouts) < total_rollouts:
                agent_run_id, event = await event_queue.get()

                # Get the rollout state
                state = rollout_states[agent_run_id]

                # Process the event
                if isinstance(event, RolloutErrorEvent):
                    cf_idea_or_base_context = None
                    replica_idx = state.metadata.replica_idx

                    for cf_or_base, policy_config in all_policies:
                        if state.metadata.counterfactual_id == cf_or_base.id:
                            cf_idea_or_base_context = cf_or_base
                            break

                    if cf_idea_or_base_context:
                        agent_run, metadata = await self._create_errored_agent_run(
                            agent_run_id=agent_run_id,
                            transcript_id=state.transcript.id,
                            cf_idea_or_base_context=cf_idea_or_base_context,
                            replica_idx=replica_idx,
                            subject_model=self.subject_model_with_client.model,
                            exception=event.error,
                            user_error_message=event.user_error_message,
                        )

                        self.result.agent_runs[agent_run_id] = agent_run
                        self.result.agent_run_metadata[agent_run_id] = metadata

                        # Mark as completed
                        completed_rollouts.add(agent_run_id)
                        completed_rollouts_count += 1
                        self.result.experiment_status.progress = (
                            completed_rollouts_count / total_rollouts
                        )

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

                    state.tool_calls_by_message[event.message_id][event.tool_call_index] = (
                        ToolCallTrackingData(
                            id=event.tool_call_id,
                            name=event.function_name,
                            arguments="",
                            type=getattr(
                                event, "type", "function"
                            ),  # Default to 'function' if not specified
                        )
                    )

                elif isinstance(event, ToolCallDelta):
                    # Accumulate tool call arguments
                    if event.message_id in state.tool_calls_by_message:
                        if event.tool_call_index in state.tool_calls_by_message[event.message_id]:
                            state.tool_calls_by_message[event.message_id][event.tool_call_index][
                                "arguments"
                            ] += event.arguments_delta

                elif isinstance(event, ToolCallEnd):
                    # Tool call is complete, no additional processing needed here
                    pass

                elif isinstance(event, MessageEnd):
                    # Message is complete, add tool calls if any exist for this message
                    if event.message_id in state.messages_by_id:
                        msg = state.messages_by_id[event.message_id]

                        # If this is an assistant message and we have tool calls, add them
                        if (
                            isinstance(msg, AssistantMessage)
                            and event.message_id in state.tool_calls_by_message
                        ):
                            tool_calls: list[ToolCall] = []
                            for tool_data in state.tool_calls_by_message[event.message_id].values():

                                # For function calls, try to parse arguments as JSON
                                parsed_args: dict[str, Any]
                                try:
                                    parsed_args = (
                                        json.loads(tool_data["arguments"])
                                        if tool_data["arguments"]
                                        else {}
                                    )
                                except json.JSONDecodeError:
                                    # If parsing fails, store as dict with raw key
                                    parsed_args = {"raw": tool_data["arguments"]}

                                tool_calls.append(
                                    ToolCall(
                                        id=tool_data["id"],
                                        function=tool_data["name"],
                                        arguments=parsed_args,
                                        type="function",
                                    )
                                )

                            msg.tool_calls = tool_calls
                            # Clean up tool calls tracking for this message
                            del state.tool_calls_by_message[event.message_id]

                        # Remove message from active messages map
                        del state.messages_by_id[event.message_id]

                elif isinstance(event, (RolloutEndEvent, GradeStart, GradeUpdate)):
                    # TODO we're not streaming grading right now. I think this is probably
                    # okay, but we could add it in the future if we want.
                    pass

                elif isinstance(event, GradeEnd):  # type: ignore[misc]
                    # Grading complete - update metadata with grade
                    state.metadata.grade = event.annotation.grade
                    state.metadata.state = "completed"

                    # Update the agent run's metadata with the grade and grader output
                    agent_run = self.result.agent_runs[agent_run_id]
                    agent_run.metadata["grade"] = event.annotation.grade
                    agent_run.metadata["grader_output"] = event.annotation.grader_response

                    # Mark this rollout as complete
                    completed_rollouts.add(agent_run_id)
                    completed_rollouts_count += 1
                    self.result.experiment_status.progress = (
                        completed_rollouts_count / total_rollouts
                    )

                yield self.result

        # Do not mark as completed here. The job will be marked completed
        # after results are stored to Docent to ensure the final streamed
        # state includes collection metadata.
