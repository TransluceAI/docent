import enum
import re
from typing import Any, Protocol
from uuid import uuid4

from pydantic import BaseModel, Field, field_serializer

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import ChatMessage
from docent.data_models.citation import Citation, parse_citations
from docent.data_models.remove_invalid_citation_ranges import remove_invalid_citation_ranges
from docent.data_models.transcript import TEXT_RANGE_CITE_INSTRUCTION
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import MessagesInput, get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES, ModelOption

logger = get_logger(__name__)

RUBRIC_PROMPT = f"""
Here is a rubric for a behavior we are looking for in transcripts of AI agent runs. You are checking for occurrences of a rubric match in the provided run.

Rubric:
{{rubric}}

Agent run:
{{agent_run}}

Reason through each part of the rubric carefully to determine whether the agent run exhibits the rubric behavior.
For every instance of a rubric match, walk through your reasoning step-by-step, justifying why the instance is a match.
It is possible that the agent does not exhibit the rubric behavior. If so, return "N/A" and nothing else; do not explain why there are no matches.

Return all justifications for each rubric match instance in the following exact format:
<instance>
...
</instance>

{TEXT_RANGE_CITE_INSTRUCTION}
- Outside of citations, do not refer to transcript numbers or block numbers.
- Outside of citations, avoid quoting or paraphrasing the transcript. Focus on describing high-level patterns.
- Be concise. Focus on the most important aspects of the agent's behavior. In most cases, 1 paragraph per match instance is enough.
"""


class Rubric(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1
    rubric_text: str
    judge_model: ModelOption | None = None


def _parse_rubric_outputs(output: LLMOutput) -> list[str] | None:
    if output.first_text is None:
        return None
    elif output.first_text.strip().upper() == "N/A":
        return []
    else:
        # Pattern matches text between <instance> and </instance> tags
        pattern = r"<instance>\n?(.*?)\n?</instance>"
        matches = re.finditer(pattern, output.first_text, re.DOTALL)
        return [str(match.group(1).strip()) for match in matches]


class ResultType(enum.Enum):
    """Enum for the type of result that a judge result can have."""

    DIRECT_RESULT = "direct_result"
    NEAR_MISS = "near_miss"


class JudgeResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    rubric_id: str
    rubric_version: int
    value: str | None = None
    result_type: ResultType

    @field_serializer("result_type")
    def serialize_result_type(self, result_type: ResultType) -> str:
        return result_type.value


class JudgeResultWithCitations(JudgeResult):
    citations: list[Citation] | None

    @classmethod
    def from_judge_result(cls, result: JudgeResult) -> "JudgeResultWithCitations":
        jrwc = cls(**result.model_dump(), citations=[])
        if result.value is not None:
            cleaned_text, citations = parse_citations(result.value)
            jrwc.value = cleaned_text
            jrwc.citations = citations
        return jrwc


class JudgeResultStreamingCallback(Protocol):
    """Supports batched streaming for cases where many search results are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        batch_index: int,
        judge_results: list[JudgeResult] | None,
    ) -> None: ...


def _validate_rubric_results(results: list[str] | None, agent_run: AgentRun) -> list[str] | None:
    """Validate and filter citation text ranges in rubric results.

    Args:
        results: Raw results from LLM judge
        agent_run: Agent run containing transcript data for validation

    Returns:
        List of validated result strings with invalid citations removed
    """
    if results is None:
        return None

    validated_values: list[str] = []

    for value in results:
        # Parse citations and validate them in one pass
        validated_text = remove_invalid_citation_ranges(value, agent_run)
        validated_values.append(validated_text)

        if validated_text != value:
            logger.info(
                f"Citation validation removed invalid text range from citation in judge result. "
                f"Agent run ID: {agent_run.id}, "
                f"Original text: {value}, "
                f"Validated text: {validated_text}, "
            )

    return validated_values


def _get_llm_callback(
    rubric_id: str,
    rubric_version: int,
    agent_run_ids: list[str],
    agent_runs: list[AgentRun],
    callback: JudgeResultStreamingCallback,
    result_type: ResultType,
):
    async def _llm_callback(batch_index: int, llm_output: LLMOutput):
        results = _parse_rubric_outputs(llm_output)

        # Return nothing if the LLM call failed (hence None)
        if results is None:
            await callback(batch_index, None)
        else:
            # Validate citations and clean up text
            validated_values = _validate_rubric_results(results, agent_runs[batch_index])
            if validated_values is None:
                validated_values = [None]

            await callback(
                batch_index,
                [
                    JudgeResult(
                        agent_run_id=agent_run_ids[batch_index],
                        rubric_id=rubric_id,
                        rubric_version=rubric_version,
                        value=value,
                        result_type=result_type,
                    )
                    for value in validated_values
                ],
            )

    return _llm_callback


def _get_prompt_resolver(rubric: Rubric, ar: AgentRun, prompt_template: str):
    def _prompt_resolver() -> list[ChatMessage | dict[str, Any]]:
        return [
            {
                "role": "user",
                "content": prompt_template.format(
                    rubric=rubric.rubric_text, agent_run=ar.text_blocks
                ),
            }
        ]

    return _prompt_resolver


async def evaluate_rubric(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    api_key_overrides: dict[str, str] | None = None,
    callback: JudgeResultStreamingCallback | None = None,
):
    prompt_resolvers: list[MessagesInput] = [
        _get_prompt_resolver(rubric, ar, RUBRIC_PROMPT) for ar in agent_runs
    ]
    outputs = await get_llm_completions_async(
        prompt_resolvers,
        get_model_options_for_rubric(rubric),
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        api_key_overrides=api_key_overrides,
        completion_callback=(
            _get_llm_callback(
                rubric.id,
                rubric.version,
                [ar.id for ar in agent_runs],
                agent_runs,
                callback,
                ResultType.DIRECT_RESULT,
            )
            if callback is not None
            else None
        ),
    )

    ans: list[list[str] | None] = [None] * len(prompt_resolvers)
    for i, output in enumerate(outputs):
        results = _parse_rubric_outputs(output)
        agent_run = agent_runs[i]
        validated_results = _validate_rubric_results(results, agent_run)
        ans[i] = validated_results if validated_results else None

    return ans


RUBRIC_MAX_RECALL_PROMPT = f"""
We are currently engaging in a rubric refinement process where a user comes in with a vague idea of a behavior they are looking for in a dataset of AI agent run transcripts. Our job is to collaborate with the user to write out a concrete specification of what they are looking for - i.e., create and refine a rubric.

This is challenging because the user themselves may not fully understand what they are looking for. Therefore, while we elicit the user's intent, we also may show them information that will change *their* conception of the goal. The general principle is that we want to extract maximum feedback from the user while requiring minimal effort on their part.

Their initial rubric was:
<rubric>
{{rubric}}
</rubric>

Here is one specific agent run:
{{agent_run}}

Your job is to find concrete examples of behavior in this agent run that might be clarifying or illuminating for the user to see.
- Instances that you would consider to match the rubric are excellent choices to show, so you can confirm that the user agrees with your judgments.
- Instances that you are uncertain about but think could plausibly match are also excellent because the user may find it useful to clarify ambiguous examples and see things that they may not have thought of themselves.
- It is also possible that you may not see anything that could plausibly be conceived of as the rubric. In that case, you should just return "N/A" only and do not include a final explanation.

Return all relevant instances of the rubric in the following exact format:
<instance>
...
</instance>

{TEXT_RANGE_CITE_INSTRUCTION}
"""


def get_model_options_for_rubric(rubric: Rubric) -> list[ModelOption]:
    if rubric.judge_model is not None:
        # If the user asked for a specific model, we shouldn't silently fall back to another one
        return [rubric.judge_model]
    else:
        return PROVIDER_PREFERENCES.evaluate_rubric


async def evaluate_rubric_max_recall(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    api_key_overrides: dict[str, str] | None = None,
    callback: JudgeResultStreamingCallback | None = None,
):
    prompt_resolvers: list[MessagesInput] = [
        _get_prompt_resolver(rubric, ar, RUBRIC_MAX_RECALL_PROMPT) for ar in agent_runs
    ]
    outputs = await get_llm_completions_async(
        prompt_resolvers,
        PROVIDER_PREFERENCES.evaluate_rubric_max_recall,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        api_key_overrides=api_key_overrides,
        completion_callback=(
            _get_llm_callback(
                rubric.id,
                rubric.version,
                [ar.id for ar in agent_runs],
                agent_runs,
                callback,
                ResultType.NEAR_MISS,
            )
            if callback is not None
            else None
        ),
    )

    ans: list[list[str] | None] = [None] * len(prompt_resolvers)
    for i, output in enumerate(outputs):
        results = _parse_rubric_outputs(output)
        ans[i] = _validate_rubric_results(results, agent_runs[i])

    return ans
