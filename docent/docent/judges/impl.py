import random
from abc import ABC, abstractmethod
from typing import Any

import anyio
import yaml
from tqdm.auto import tqdm

from docent._llm_util.data_models.exceptions import ValidationFailedException
from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.llm_svc import BaseLLMService
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.judges.types import JudgeResult, JudgeVariant, ResultType, Rubric
from docent.judges.util.parse_output import parse_and_validate_llm_output
from docent.judges.util.voting import (
    JudgeOutputDistribution,
    compute_output_distributions,
    find_modal_result,
    get_agreement_keys,
)

logger = get_logger(__name__)


class BaseJudge(ABC):
    def __init__(self, cfg: Rubric, llm_svc: BaseLLMService):
        self.cfg = cfg
        self.llm_svc = llm_svc

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
            parse_and_validate_llm_output(llm_output, self.cfg.output_schema, agent_run)

        return _validation_callback

    async def single_rollout(self, agent_run: AgentRun) -> dict[str, Any] | None:
        prompt = [{"role": "system", "content": self.cfg.materialize_system_prompt(agent_run)}]
        outputs = await self.llm_svc.get_completions(
            inputs=[prompt],
            model_options=[self.cfg.judge_model],
            max_new_tokens=16384,
            timeout=180.0,
            use_cache=False,
            validation_callback=self._get_validation_callback(agent_run),
        )
        output = outputs[0]

        try:
            validated_output = parse_and_validate_llm_output(
                output, self.cfg.output_schema, agent_run
            )
            return validated_output
        except ValidationFailedException:
            return None


class SingleRolloutJudge(BaseJudge):
    """Rolls out the judge once."""

    def __init__(self, cfg: Rubric, llm_svc: BaseLLMService):
        super().__init__(cfg, llm_svc)

    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        output = await self.single_rollout(agent_run)
        if output is None:
            return None
        else:
            return JudgeResult(
                agent_run_id=agent_run.id,
                rubric_id=self.cfg.id,
                rubric_version=self.cfg.version,
                output=output,
                result_type=ResultType.DIRECT_RESULT,
            )


class MajorityVotingJudge(BaseJudge):
    """Rolls out the judge multiple times, then uses majority voting to determine the final result."""

    def __init__(self, cfg: Rubric, llm_svc: BaseLLMService):
        super().__init__(cfg, llm_svc)

    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        indep_results: list[dict[str, Any]] = []

        async def _execute():
            result = await self.single_rollout(agent_run)
            if result is not None:
                indep_results.append(result)

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
        pbar = tqdm(total=n_initial_rollouts_to_sample, desc="Independent rollouts")

        async def _execute():
            result = await self.single_rollout(agent_run)
            if result is not None:
                indep_results.append(result)
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

        return distributions, {"first_step_rollouts": indep_results}


class MultiReflectionJudge(BaseJudge):
    """Rolls out the judge multiple times, then uses reflection to determine the final result."""

    def __init__(self, cfg: Rubric, llm_svc: BaseLLMService):
        super().__init__(cfg, llm_svc)

    async def single_rollout_second_stage(
        self, agent_run: AgentRun, first_stage_results: list[dict[str, Any]]
    ) -> dict[str, Any] | None:
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
        output = outputs[0]

        try:
            validated_output = parse_and_validate_llm_output(
                output, self.cfg.output_schema, agent_run
            )
            return validated_output
        except ValidationFailedException:
            return None

    async def __call__(self, agent_run: AgentRun) -> JudgeResult | None:
        rubric = self.cfg

        indep_results: list[dict[str, Any]] = []

        async def _execute():
            result = await self.single_rollout(agent_run)
            if result is not None:
                indep_results.append(result)

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
        final_results = indep_results.copy()  # Shallow copy
        if len(indep_results) > 1:
            candidate_final_results: list[dict[str, Any]] = []

            async def _execute_second_stage():
                result = await self.single_rollout_second_stage(agent_run, indep_results)
                if result is not None:
                    candidate_final_results.append(result)

            async with anyio.create_task_group() as tg:
                for _ in range(self.cfg.n_rollouts_per_input):
                    tg.start_soon(_execute_second_stage)

            # Use reflected results if we got any, otherwise fall back to original results
            if candidate_final_results:
                final_results = candidate_final_results
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
                # Also include initial measurements
                "indep_results": indep_results,
                "indep_max_idx": indep_max_idx,
                "indep_agt_key_modes_and_counts": indep_agt_key_modes_and_counts,
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
        first_step_combinations: list[list[dict[str, Any]]] = []
        second_step_rollouts: list[list[dict[str, Any]]] = []

        ##########
        # Step 1 #
        ##########

        pbar_first = tqdm(total=n_initial_rollouts_to_sample, desc="Stage 1: Initial rollouts")

        async def _execute_first_stage():
            result = await self.single_rollout(agent_run)
            if result is not None:
                first_step_rollouts.append(result)
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

        ##########
        # Step 2 #
        ##########

        pbar_second = tqdm(total=n_combinations_to_sample, desc="Stage 2: Combinations")

        async with anyio.create_task_group() as tg_second:

            async def _execute_second_stage(i: int, combination: list[dict[str, Any]]):
                pbar_third = tqdm(
                    total=n_reflection_rollouts_to_sample,
                    desc=f"Stage 2: Combination {i+1}/{n_combinations_to_sample}",
                )

                async def _execute_second_stage_inner():
                    result = await self.single_rollout_second_stage(agent_run, combination)
                    if result is not None:
                        second_step_rollouts[i].append(result)
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
            "first_step_combinations": first_step_combinations,
            "second_step_rollouts": second_step_rollouts,
        }


def build_judge(rubric: Rubric, llm_svc: BaseLLMService):
    if rubric.judge_variant == JudgeVariant.MAJORITY:
        return MajorityVotingJudge(rubric, llm_svc)
    elif rubric.judge_variant == JudgeVariant.MULTI_REFLECT:
        return MultiReflectionJudge(rubric, llm_svc)
    raise ValueError(f"Invalid variant: {rubric.judge_variant}")
