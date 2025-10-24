import random
import re
from abc import ABC, abstractmethod
from contextlib import nullcontext
from typing import Any, Sequence

import anyio
import yaml
from pydantic_core import to_jsonable_python
from tqdm.auto import tqdm

from docent._llm_util.data_models.exceptions import ValidationFailedException
from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.llm_svc import BaseLLMService
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat.message import (
    AssistantMessage,
    ChatMessage,
    ToolMessage,
    UserMessage,
)
from docent.data_models.chat.tool import ToolInfo
from docent.judges.types import JudgeResult, JudgeVariant, ResultType, Rubric
from docent.judges.util.parse_output import parse_and_validate_output_str
from docent.judges.util.voting import (
    JudgeOutputDistribution,
    compute_output_distributions,
    find_modal_result,
    get_agreement_keys,
)
from docent.trace import agent_run_context, agent_run_metadata

logger = get_logger(__name__)


class BaseJudge(ABC):
    def __init__(
        self, cfg: Rubric, llm_svc: BaseLLMService, docent_collection_id: str | None = None
    ):
        self.cfg = cfg
        self.llm_svc = llm_svc
        self.docent_collection_id = docent_collection_id

    @abstractmethod
    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        """Returns None if all rollouts failed to produce a valid output."""

    @abstractmethod
    async def estimate_output_distrs(
        self, agent_run: AgentRun, **kwargs: Any
    ) -> None | tuple[dict[str, JudgeOutputDistribution], dict[str, Any]]:
        """Estimate the output distribution of each output key."""

    def _get_validation_callback(self, agent_run: AgentRun):
        async def _validation_callback(batch_index: int, llm_output: LLMOutput):
            validated_output = self._validate_first_response_tag_or_entire_output(
                llm_output.first_text or "", agent_run
            )
            if validated_output is None:
                raise ValidationFailedException(
                    "Validation failed", failed_output=llm_output.first_text
                )

        return _validation_callback

    async def one_rollout(
        self, agent_run: AgentRun
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        with agent_run_context() if self.docent_collection_id is not None else nullcontext():
            if self.cfg.rollout_type == "single_turn":
                output, metadata = await self.one_single_turn_rollout(agent_run)
            elif self.cfg.rollout_type == "multi_turn":
                output, metadata = await self.one_multi_turn_rollout(
                    agent_run, max_turns=10, max_steps_per_turn=5
                )
            else:
                raise ValueError(f"Invalid rollout type: {self.cfg.rollout_type}")

            if self.docent_collection_id is not None:
                agent_run_metadata(
                    {
                        "agent_run_id": agent_run.id,
                        "judge_output": output,
                        "judge_rollout_metadata": to_jsonable_python(metadata),
                    }
                )

        return output, metadata

    def _validate_first_response_tag_or_entire_output(
        self, output_str: str, agent_run: AgentRun
    ) -> dict[str, Any] | None:
        """Validate the first <response> tag in the output string.
        For backward compatibility, also try to validate the entire output as JSON, for
            old system prompts that don't ask for <response> tags.

        Args:
            output_str: The output string to validate
            agent_run: The agent run to validate against

        Returns:
            The validated output if successful, None otherwise
        """
        response_matches = re.findall(r"<response>(.*?)</response>", output_str, re.DOTALL)

        # Try to validate any match; take the first
        for response_text in response_matches:
            try:
                validated_output = parse_and_validate_output_str(
                    response_text, self.cfg.output_schema, agent_run
                )
                return validated_output
            except ValidationFailedException:
                continue  # Try the next match if validation fails

        # Try to validate the entire output as JSON
        # But only if the output _didn't_ contain a <response>...</response> tag
        if not response_matches:
            try:
                validated_output = parse_and_validate_output_str(
                    output_str, self.cfg.output_schema, agent_run
                )
                return validated_output
            except ValidationFailedException:
                pass

        return None

    ########################
    # Single turn rollouts #
    ########################

    async def one_single_turn_rollout(
        self, agent_run: AgentRun
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        prompt = [UserMessage(content=self.cfg.materialize_system_prompt(agent_run))]
        outputs = await self.llm_svc.get_completions(
            inputs=[prompt],
            model_options=[self.cfg.judge_model],
            max_new_tokens=16384,
            timeout=180.0,
            use_cache=False,
            validation_callback=self._get_validation_callback(agent_run),
        )
        output_str = outputs[0].first_text

        # Extract all <response>...</response> tags from the current message
        validated_output = self._validate_first_response_tag_or_entire_output(
            output_str or "", agent_run
        )
        if validated_output is not None:
            return validated_output, {"full_output": output_str}
        else:
            return None, None

    #######################
    # Multi-turn rollouts #
    #######################

    async def one_multi_turn_rollout(
        self, agent_run: AgentRun, max_turns: int, max_steps_per_turn: int
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        msgs = [UserMessage(content=self.cfg.materialize_system_prompt(agent_run))]
        for _ in range(max_turns):
            msgs = await self.agent_one_turn(msgs, max_steps_per_turn=max_steps_per_turn)

            last_msg_content = msgs[-1].text if msgs else None
            # Extract all <response>...</response> tags from the current message
            # Return if we find a valid response; otherwise, continue
            validated_output = self._validate_first_response_tag_or_entire_output(
                last_msg_content or "", agent_run
            )
            if validated_output is not None:
                # When returning, strip out the system message, which duplicates the agent run
                # content many times.
                return validated_output, {"rollout_messages": msgs[1:]}

        # No <response>...</response> tags with valid JSON,so return None
        return None, None

    async def agent_one_turn(self, init_msgs: Sequence[ChatMessage], max_steps_per_turn: int):
        """Given a list of messages, run one turn of the agent.
        The agent may invoke tools, so we loop until there are no more to handle.
        """

        msgs = list(init_msgs)  # Shallow copy is fine
        for _ in range(max_steps_per_turn):
            last_msg = msgs[-1]
            if last_msg.role == "system" or last_msg.role == "user" or last_msg.role == "tool":
                outputs = await self.llm_svc.get_completions(
                    inputs=[msgs],
                    model_options=[self.cfg.judge_model],
                    tools=[
                        ToolInfo(
                            name="step_finished",
                            description="Call this tool to indicate that you have finished one step in the decision procedure",
                        )
                    ],
                    max_new_tokens=16384,
                    timeout=180.0,
                    use_cache=False,
                )
                output = outputs[0].first
                if output is None:
                    # FIXME(mengk): handle empty completion
                    raise ValueError("Empty completion in agent one turn")
                new_assistant_msg = AssistantMessage(
                    content=output.text or "", tool_calls=output.tool_calls
                )
                msgs.append(new_assistant_msg)
            elif last_msg.role == "assistant":
                if last_msg.tool_calls is not None:
                    msgs.extend(
                        [
                            ToolMessage(
                                content="Step completed",
                                tool_call_id=tool_call.id,
                            )
                            for tool_call in last_msg.tool_calls
                        ]
                    )
                else:
                    break  # Terminate if there are no more tool calls to handle
            else:
                raise ValueError(f"Unknown message role: {last_msg.role}")
        return msgs


class SingleRolloutJudge(BaseJudge):
    """Rolls out the judge once."""

    def __init__(self, cfg: Rubric, llm_svc: BaseLLMService):
        super().__init__(cfg, llm_svc)

    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        output, metadata = await self.one_rollout(agent_run)
        if output is None:
            return None
        else:
            return JudgeResult(
                agent_run_id=agent_run.id,
                rubric_id=self.cfg.id,
                rubric_version=self.cfg.version,
                output=output,
                result_metadata={"rollout_metadata": metadata},
                result_type=ResultType.DIRECT_RESULT,
            )


class MajorityVotingJudge(BaseJudge):
    """Rolls out the judge multiple times, then uses majority voting to determine the final result."""

    def __init__(
        self, cfg: Rubric, llm_svc: BaseLLMService, docent_collection_id: str | None = None
    ):
        super().__init__(cfg, llm_svc, docent_collection_id)

    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        indep_results: list[dict[str, Any]] = []
        indep_rollout_metadata: list[dict[str, Any] | None] = []

        async def _execute():
            result, metadata = await self.one_rollout(agent_run)
            if result is not None:
                indep_results.append(result)
                indep_rollout_metadata.append(metadata)

        # Run rollouts concurrently
        async with anyio.create_task_group() as tg:
            for _ in range(self.cfg.n_rollouts_per_input):
                tg.start_soon(_execute)
        if not indep_results:
            return None

        # Get a list of the keys that we want to measure agreement on
        agreement_keys = get_agreement_keys(self.cfg.output_schema)

        # Find the result that best matches modal values
        final_max_idx, final_agt_key_modes_and_counts = find_modal_result(
            indep_results, agreement_keys
        )
        final_output = indep_results[final_max_idx]

        # Compute the distribution of the output across the agreement keys
        final_output_distributions = compute_output_distributions(
            indep_results, self.cfg.output_schema, agreement_keys
        )

        return JudgeResult(
            agent_run_id=agent_run.id,
            rubric_id=self.cfg.id,
            rubric_version=self.cfg.version,
            output=final_output,
            result_metadata={
                "agt_keys": agreement_keys,
                # Final measurements
                "final_results": indep_results,
                "final_agt_key_modes_and_counts": final_agt_key_modes_and_counts,
                "final_max_idx": final_max_idx,
                "final_output_distributions": final_output_distributions,
                "final_rollout_metadata": indep_rollout_metadata,
            },
            result_type=ResultType.DIRECT_RESULT,
        )

    async def estimate_output_distrs(
        self, agent_run: AgentRun, *, n_initial_rollouts_to_sample: int, **kwargs: Any
    ) -> None | tuple[dict[str, JudgeOutputDistribution], dict[str, Any]]:
        if self.cfg.n_rollouts_per_input > n_initial_rollouts_to_sample:
            raise ValueError(
                "n_initial_rollouts_to_sample must be greater than or equal to cfg.n_rollouts_per_input"
            )

        indep_results: list[dict[str, Any]] = []
        indep_rollout_metadata: list[dict[str, Any] | None] = []
        pbar = tqdm(total=n_initial_rollouts_to_sample, desc="Independent rollouts", leave=False)

        async def _execute():
            result, metadata = await self.one_rollout(agent_run)
            if result is not None:
                indep_results.append(result)
                indep_rollout_metadata.append(metadata)
            pbar.update(1)

        # Run rollouts concurrently
        async with anyio.create_task_group() as tg:
            for _ in range(n_initial_rollouts_to_sample):
                tg.start_soon(_execute)

        pbar.close()

        if not indep_results:
            return None

        # Compute the probability vector for each agreement key
        distributions = compute_output_distributions(
            indep_results, self.cfg.output_schema, get_agreement_keys(self.cfg.output_schema)
        )

        return distributions, {
            "first_step_rollouts": indep_results,
            "first_step_rollout_metadata": indep_rollout_metadata,
        }


class MultiReflectionJudge(BaseJudge):
    """Rolls out the judge multiple times, then uses reflection to determine the final result."""

    def __init__(
        self, cfg: Rubric, llm_svc: BaseLLMService, docent_collection_id: str | None = None
    ):
        super().__init__(cfg, llm_svc, docent_collection_id)

    async def one_rollout_second_stage(
        self, agent_run: AgentRun, first_stage_results: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """Reflect on the results of the first stage of rollouts.
        TODO(mengk): this is only done in a single-turn way. We should generalize this to multi-turn.
        """

        # Construct *single* reflection prompt
        first_stage_results_text = "\n\n".join(
            [
                f"Rollout {j+1}:\n{yaml.dump(r, width=float('inf'))}"
                for j, r in enumerate(first_stage_results)
            ]
        )
        reflection_instruction = (
            f"We have sampled a judge {len(first_stage_results)} times to get {len(first_stage_results)} independent answers to the same rubric evaluation:\n"
            f"{first_stage_results_text}\n\n"
            f"Please reflect on these answers. Consider all the information and evidence presented. "
            f"Return a final answer in the same JSON format as before."
        )
        reflection_prompt = [
            # Original system prompt
            {"role": "system", "content": self.cfg.materialize_system_prompt(agent_run)},
            # Additional reflection instruction as a user message (kind of awkward)
            {"role": "user", "content": reflection_instruction},
        ]

        # Ask the judge to reflect on the others' results
        outputs = await self.llm_svc.get_completions(
            inputs=[reflection_prompt],
            model_options=[self.cfg.judge_model],
            max_new_tokens=16384,
            timeout=180.0,
            use_cache=False,
            validation_callback=self._get_validation_callback(agent_run),
        )
        output_str = outputs[0].first_text

        validated_output = self._validate_first_response_tag_or_entire_output(
            output_str or "", agent_run
        )
        if validated_output is not None:
            return validated_output, None
        else:
            return None, None

    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        rubric = self.cfg

        indep_results: list[dict[str, Any]] = []
        indep_rollout_metadata: list[dict[str, Any] | None] = []

        async def _execute():
            result, metadata = await self.one_rollout(agent_run)
            if result is not None:
                indep_results.append(result)
                indep_rollout_metadata.append(metadata)

        # Stage 1: run rollouts concurrently
        async with anyio.create_task_group() as tg:
            for _ in range(self.cfg.n_rollouts_per_input):
                tg.start_soon(_execute)
        if not indep_results:
            return None

        # Compute initial modes
        agreement_keys = get_agreement_keys(rubric.output_schema)
        indep_max_idx, indep_agt_key_modes_and_counts = find_modal_result(
            indep_results, agreement_keys
        )

        # Stage 2: reflect on the results
        # Shallow copies are fine
        final_results = indep_results.copy()
        final_rollout_metadata = indep_rollout_metadata.copy()
        if len(indep_results) > 1:
            candidate_final_results: list[dict[str, Any]] = []
            candidate_final_rollout_metadata: list[dict[str, Any] | None] = []

            async def _execute_second_stage():
                result, metadata = await self.one_rollout_second_stage(agent_run, indep_results)
                if result is not None:
                    candidate_final_results.append(result)
                    candidate_final_rollout_metadata.append(metadata)

            async with anyio.create_task_group() as tg:
                for _ in range(self.cfg.n_rollouts_per_input):
                    tg.start_soon(_execute_second_stage)

            # Use reflected results if we got any, otherwise fall back to original results
            if candidate_final_results:
                final_results = candidate_final_results
                final_rollout_metadata = candidate_final_rollout_metadata
            else:
                logger.warning("No reflected results found, falling back to original results")

        final_max_idx, final_agt_key_modes_and_counts = find_modal_result(
            final_results, agreement_keys
        )
        return JudgeResult(
            agent_run_id=agent_run.id,
            rubric_id=rubric.id,
            rubric_version=rubric.version,
            output=final_results[final_max_idx],
            result_metadata={
                "agt_keys": agreement_keys,
                # Final measurements
                "final_results": final_results,
                "final_agt_key_modes_and_counts": final_agt_key_modes_and_counts,
                "final_max_idx": final_max_idx,
                "final_rollout_metadata": final_rollout_metadata,
                # Also include initial measurements
                "indep_results": indep_results,
                "indep_max_idx": indep_max_idx,
                "indep_agt_key_modes_and_counts": indep_agt_key_modes_and_counts,
                "indep_rollout_metadata": indep_rollout_metadata,
            },
            result_type=ResultType.DIRECT_RESULT,
        )

    async def estimate_output_distrs(
        self,
        agent_run: AgentRun,
        *,
        n_initial_rollouts_to_sample: int,
        n_combinations_to_sample: int,
        n_reflection_rollouts_to_sample: int,
        **kwargs: Any,
    ) -> None | tuple[dict[str, JudgeOutputDistribution], dict[str, Any]]:
        if self.cfg.n_rollouts_per_input > n_initial_rollouts_to_sample:
            raise ValueError(
                "n_initial_rollouts_to_sample must be greater than or equal to cfg.n_rollouts_per_input"
            )
        if self.cfg.n_rollouts_per_input > n_reflection_rollouts_to_sample:
            raise ValueError(
                "n_reflection_rollouts_to_sample must be greater than or equal to cfg.n_rollouts_per_input"
            )

        first_step_rollouts: list[dict[str, Any]] = []
        first_step_rollout_metadata: list[dict[str, Any] | None] = []
        first_step_combinations: list[list[dict[str, Any]]] = []
        second_step_rollouts: list[list[dict[str, Any]]] = []
        second_step_rollout_metadata: list[list[dict[str, Any] | None]] = []

        ##########
        # Step 1 #
        ##########

        pbar_first = tqdm(
            total=n_initial_rollouts_to_sample, desc="Stage 1: Initial rollouts", leave=False
        )

        async def _execute_first_stage():
            result, metadata = await self.one_rollout(agent_run)
            if result is not None:
                first_step_rollouts.append(result)
                first_step_rollout_metadata.append(metadata)
            pbar_first.update(1)

        # Collect rollouts of the first stage
        async with anyio.create_task_group() as tg_first:
            for _ in range(n_initial_rollouts_to_sample):
                tg_first.start_soon(_execute_first_stage)

        pbar_first.close()

        if len(first_step_rollouts) < self.cfg.n_rollouts_per_input:
            raise ValueError("Not enough first step rollouts to sample combinations")

        # Sample random k-sized combinations of the first step rollouts
        for _ in range(n_combinations_to_sample):
            combination = random.sample(first_step_rollouts, self.cfg.n_rollouts_per_input)
            first_step_combinations.append(combination)
            second_step_rollouts.append([])
            second_step_rollout_metadata.append([])

        ##########
        # Step 2 #
        ##########

        pbar_second = tqdm(
            total=n_combinations_to_sample, desc="Stage 2: Combinations", leave=False
        )

        async with anyio.create_task_group() as tg_second:

            async def _execute_second_stage(i: int, combination: list[dict[str, Any]]):
                pbar_third = tqdm(
                    total=n_reflection_rollouts_to_sample,
                    desc=f"Stage 2: Combination {i+1}/{n_combinations_to_sample}",
                    leave=False,
                )

                async def _execute_second_stage_inner():
                    result, metadata = await self.one_rollout_second_stage(agent_run, combination)
                    if result is not None:
                        second_step_rollouts[i].append(result)
                        second_step_rollout_metadata[i].append(metadata)
                    pbar_third.update(1)

                async with anyio.create_task_group() as tg:
                    for _ in range(n_reflection_rollouts_to_sample):
                        tg.start_soon(_execute_second_stage_inner)

                pbar_third.close()
                pbar_second.update(1)

            for i, combination in enumerate(first_step_combinations):
                tg_second.start_soon(_execute_second_stage, i, combination)

        pbar_second.close()

        output_distributions = compute_output_distributions(
            [sublist for el in second_step_rollouts for sublist in el],
            self.cfg.output_schema,
            get_agreement_keys(self.cfg.output_schema),
        )

        return output_distributions, {
            "first_step_rollouts": first_step_rollouts,
            "first_step_rollout_metadata": first_step_rollout_metadata,
            "first_step_combinations": first_step_combinations,
            "second_step_rollouts": second_step_rollouts,
            "second_step_rollout_metadata": second_step_rollout_metadata,
        }


def build_judge(rubric: Rubric, llm_svc: BaseLLMService, docent_collection_id: str | None = None):
    if rubric.judge_variant == JudgeVariant.MAJORITY:
        return MajorityVotingJudge(rubric, llm_svc, docent_collection_id)
    elif rubric.judge_variant == JudgeVariant.MULTI_REFLECT:
        return MultiReflectionJudge(rubric, llm_svc, docent_collection_id)
    raise ValueError(f"Invalid variant: {rubric.judge_variant}")
