import json
from abc import ABC, abstractmethod
from typing import Any

from docent._llm_util.data_models.llm_output import LLMOutput
from docent._llm_util.data_models.simple_svc import BaseLLMService, SimpleLLMService
from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.judges.types import JudgeResult, ResultType, Rubric
from docent.judges.util.parse_output import parse_and_validate_llm_output
from docent.judges.util.voting import (
    compute_output_distribution,
    find_modal_result,
    get_agreement_keys,
)

logger = get_logger(__name__)


class BaseJudge(ABC):
    def __init__(self, cfg: Rubric, llm_svc: BaseLLMService):
        self.cfg = cfg
        self.llm_svc = llm_svc

    @abstractmethod
    async def __call__(self, agent_run: AgentRun, *args: Any, **kwargs: Any) -> JudgeResult | None:
        """Returns None if all rollouts failed to produce a valid output."""


class MajorityVotingJudge(BaseJudge):
    """Rolls out the judge multiple times, then uses majority voting to determine the final result."""

    def __init__(
        self,
        cfg: Rubric,
        n_rollouts_per_input: int,
        llm_svc: BaseLLMService = SimpleLLMService(),
    ):
        super().__init__(cfg, llm_svc)
        self.n_rollouts_per_input = n_rollouts_per_input

    async def __call__(
        self,
        agent_run: AgentRun,
        max_concurrency: int = 10,
    ) -> JudgeResult | None:
        async def _validation_callback(batch_index: int, llm_output: LLMOutput):
            parse_and_validate_llm_output(llm_output, self.cfg.output_schema, agent_run)

        prompt = [{"role": "user", "content": self.cfg.materialize_system_prompt(agent_run)}]
        outputs = await self.llm_svc.get_completions(
            inputs=[prompt for _ in range(self.n_rollouts_per_input)],
            model_options=[self.cfg.judge_model],
            max_new_tokens=16384,
            timeout=180.0,
            use_cache=False,
            validation_callback=_validation_callback,
            max_concurrency=max_concurrency,
        )

        # Process each rollout independently
        indep_results: list[dict[str, Any]] = []
        for output in outputs:
            if validated_output := parse_and_validate_llm_output(
                output, self.cfg.output_schema, agent_run
            ):
                indep_results.append(validated_output)

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
        final_output_distribution = compute_output_distribution(
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
                "final_output_distribution": final_output_distribution,
            },
            result_type=ResultType.DIRECT_RESULT,
        )


class MultiReflectionJudge(BaseJudge):
    """Rolls out the judge multiple times, then uses reflection to determine the final result."""

    def __init__(
        self,
        cfg: Rubric,
        n_rollouts_per_input: int,
        llm_svc: BaseLLMService = SimpleLLMService(),
    ):
        super().__init__(cfg, llm_svc)
        self.n_rollouts_per_input = n_rollouts_per_input

    async def __call__(
        self,
        agent_run: AgentRun,
        max_concurrency: int = 10,
    ) -> JudgeResult | None:
        rubric = self.cfg

        async def _validation_callback(batch_index: int, llm_output: LLMOutput):
            parse_and_validate_llm_output(llm_output, rubric.output_schema, agent_run)

        # Run several independent rollouts
        prompt = [{"role": "user", "content": self.cfg.materialize_system_prompt(agent_run)}]
        outputs = await self.llm_svc.get_completions(
            inputs=[prompt for _ in range(self.n_rollouts_per_input)],
            model_options=[rubric.judge_model],
            max_new_tokens=16384,
            timeout=180.0,
            use_cache=False,
            validation_callback=_validation_callback,
            max_concurrency=max_concurrency,
        )

        # Process each rollout
        indep_results: list[dict[str, Any]] = []
        for output in outputs:
            if output.first_text is None:
                continue
            if v_output := parse_and_validate_llm_output(output, rubric.output_schema, agent_run):
                indep_results.append(v_output)

        if not indep_results:
            return None

        # Compute initial modes
        agreement_keys = get_agreement_keys(rubric.output_schema)
        indep_max_idx, indep_agt_key_modes_and_counts = find_modal_result(
            indep_results, agreement_keys
        )

        def _get_reflection_prompt(cur_index: int):
            # Current result
            result = indep_results[cur_index]
            # Get other results (excluding the current one)
            other_results = [r for j, r in enumerate(indep_results) if j != cur_index]

            # Create the reflection message
            other_results_text = "\n\n".join(
                [f"Answer {j+1}:\n{json.dumps(r, indent=2)}" for j, r in enumerate(other_results)]
            )

            reflection_instruction = (
                f"Here are {len(other_results)} other independent answers to the same rubric evaluation:\n\n"
                f"{other_results_text}\n\n"
                f"Please reflect on these other answers and your own answer. "
                f"Consider if any of them have identified important aspects you missed, or if there are disagreements that should be resolved. "
                f"Then provide your final answer in the same JSON format as before."
            )

            # Construct the multi-message prompt
            # 1. Original user message
            # 2. Assistant message with the rollout's result
            # 3. New user message asking for reflection
            return [
                *prompt,  # Original user message(s)
                {"role": "assistant", "content": json.dumps(result, indent=2)},
                {"role": "user", "content": reflection_instruction},
            ]

        final_results = indep_results.copy()  # Shallow copy
        if len(indep_results) > 1:
            # Ask the judge to reflect on the others' results
            reflection_outputs = await self.llm_svc.get_completions(
                inputs=[_get_reflection_prompt(i) for i in range(len(indep_results))],
                model_options=[rubric.judge_model],
                max_new_tokens=16384,
                timeout=180.0,
                use_cache=False,
                validation_callback=_validation_callback,
                max_concurrency=max_concurrency,
            )

            # Process reflection outputs in the same way as the initial rollouts
            reflected_results: list[dict[str, Any]] = []
            for output in reflection_outputs:
                if output.first_text is None:
                    continue
                if v_output := parse_and_validate_llm_output(
                    output, rubric.output_schema, agent_run
                ):
                    reflected_results.append(v_output)

            # Use reflected results if we got any, otherwise fall back to original results
            if reflected_results:
                final_results = reflected_results
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
