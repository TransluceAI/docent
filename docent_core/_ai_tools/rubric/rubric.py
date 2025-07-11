import re
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, Field

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.citation import Citation, parse_citations_single_run
from docent.data_models.transcript import SINGLE_RUN_CITE_INSTRUCTION
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import get_llm_completions_async
from docent_core._llm_util.providers.preferences import ModelOption

logger = get_logger(__name__)


RUBRIC_PROMPT = f"""
You will be provided a rubric for something a user wants to find in an agent run. Your task is to check for occurrences of a rubric match in the provided run.

Rubric:
{{rubric}}

Agent run:
{{agent_run}}

First think carefully about whether the agent run contains any instances of the rubric. Guidelines:
- If something matches only an exclusion rule: NO, it should not be included.
- If something matches only an inclusion rule: YES, it should be included.
- If something matches both an inclusion and exclusion rule: YES, it should be included, since inclusion precedes exclusion.
- If something matches the high level description but no inclusion and no exclusion rules: YES, it should be included.

If there are no matches, return N/A.

For every instance of a rubric match, describe how the agent run pertains to the rubric. Be concise but specific; I should be able to mentally reconstruct the pertinent parts of the run from your description. The list should also be exhaustive.

Return all instances of the rubric in the following exact format:
<instance>
description
</instance>
...
<instance>
description
</instance>

{SINGLE_RUN_CITE_INSTRUCTION}
"""


class Rubric(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    high_level_description: str
    inclusion_rules: list[str]
    exclusion_rules: list[str]

    @property
    def text(self) -> str:
        inclusion_text = "\n".join(f"- {rule}" for rule in self.inclusion_rules)
        exclusion_text = "\n".join(f"- {rule}" for rule in self.exclusion_rules)
        return f"High level description:\n{self.high_level_description}\n\nInclusion rules:\n{inclusion_text}\n\nExclusion rules:\n{exclusion_text}"


def _parse_llm_output(output: LLMOutput) -> list[str] | None:
    if output.first_text is None:
        return None
    elif output.first_text.strip().upper() == "N/A":
        return []
    else:
        # Pattern matches text between <instance> and </instance> tags
        pattern = r"<instance>\n?(.*?)\n?</instance>"
        matches = re.finditer(pattern, output.first_text, re.DOTALL)
        return [str(match.group(1).strip()) for match in matches]


class JudgeResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    rubric_id: str
    value: str | None = None


class JudgeResultWithCitations(JudgeResult):
    citations: list[Citation] | None

    @classmethod
    def from_judge_result(cls, result: JudgeResult) -> "JudgeResultWithCitations":
        return cls(
            **result.model_dump(),
            citations=(
                parse_citations_single_run(result.value) if result.value is not None else None
            ),
        )


class JudgeResultStreamingCallback(Protocol):
    """Supports batched streaming for cases where many search results are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        judge_results: list[JudgeResult] | None,
    ) -> None: ...


def _get_llm_callback(
    rubric_id: str,
    agent_run_ids: list[str],
    callback: JudgeResultStreamingCallback,
):
    async def _llm_callback(batch_index: int, llm_output: LLMOutput):
        results = _parse_llm_output(llm_output)

        # Return nothing if the LLM call failed (hence None)
        if results is None:
            await callback(None)
        else:
            await callback(
                [
                    JudgeResult(
                        agent_run_id=agent_run_ids[batch_index],
                        rubric_id=rubric_id,
                        value=value,
                    )
                    # If there were no matches, return a single None result
                    # Otherwise, return all results
                    for value in (results if len(results) > 0 else [None])
                ]
            )

    return _llm_callback


async def evaluate_rubric(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    model_options: list[ModelOption],
    callback: JudgeResultStreamingCallback | None = None,
):
    ids = [ar.id for ar in agent_runs]
    texts = [ar.text for ar in agent_runs]

    prompts = [RUBRIC_PROMPT.format(rubric=rubric.text, agent_run=agent_run) for agent_run in texts]
    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
            for prompt in prompts
        ],
        model_options,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        completion_callback=(
            _get_llm_callback(rubric.id, ids, callback) if callback is not None else None
        ),
    )

    ans: list[list[str] | None] = [
        None,
    ] * len(texts)
    for i, output in enumerate(outputs):
        ans[i] = _parse_llm_output(output)

    # # next we search over long AgentRuns, which need to be sharded to within context length
    # # these can't be streamed immediately since we need to search over all shards first

    # long_indices = [i for i in range(len(texts)) if i not in short_indices]
    # long_ids = [ids[i] for i in long_indices]
    # long_texts = [agent_runs[i].to_text(100_000) for i in long_indices]
    # flattened_long_texts = [text for run in long_texts for text in run]
    # prompts = [
    #     RUBRIC_PROMPT.format(rubric=rubric.text, agent_run=agent_run)
    #     for agent_run in flattened_long_texts
    # ]

    # logger.info(f"Searching over {len(prompts)} long agent runs")
    # outputs = await get_llm_completions_async(
    #     [
    #         [
    #             {
    #                 "role": "user",
    #                 "content": prompt,
    #             },
    #         ]
    #         for prompt in prompts
    #     ],
    #     model_options,
    #     max_new_tokens=8192,
    #     timeout=180.0,
    #     use_cache=True,
    # )

    # grouped_outputs: list[list[LLMOutput]] = []
    # index = 0
    # for long_text in long_texts:
    #     grouped_outputs.append(outputs[index : index + len(long_text)])
    #     index += len(long_text)

    # for i, output_group in enumerate(grouped_outputs):
    #     results = [_parse_llm_output(output) for output in output_group]
    #     if any(result is None for result in results):
    #         ans[long_indices[i]] = None
    #     else:
    #         flattened_results = [r for result in results for r in cast(list[str], result)]
    #         ans[long_indices[i]] = flattened_results

    # if callback is not None:
    #     long_llm_callback = _get_llm_callback(rubric.id, long_ids, callback)
    #     callbacks = [
    #         long_llm_callback(i, output_group) for i, output_group in enumerate(grouped_outputs)
    #     ]
    #     await asyncio.gather(*callbacks)

    return ans


RULE_PROPOSAL_PROMPT = """
A user specified a rubric for something they wanted to find in an agent run. We ran that rubric over a set of agent runs and found some matches.

Your task is to review the matches and propose a concrete, unambiguous, mutually exclusive, and completely exhaustive set of rules that govern the matches. Guidelines:
- Rules must be specified very precisely, as they will be used in downstream evaluation.
- Do not propose rules that are already covered by other rules, and make sure to cover all matches.

Rubric:
{rubric}

Matches:
{matches}

Return the rules in the following exact format:
<rule>
...
</rule>
...
"""


def _parse_rules_output(output_text: str | None) -> list[str] | None:
    """Parse rules from LLM output text containing <rule>...</rule> tags."""
    if output_text is None:
        return None
    else:
        # Pattern matches text between <rule> and </rule> tags
        pattern = r"<rule>\n?(.*?)\n?</rule>"
        matches = re.finditer(pattern, output_text, re.DOTALL)
        return [str(match.group(1).strip()) for match in matches]


async def propose_rules_post_hoc(
    rubric: Rubric,
    matches: list[str],
    model_options: list[ModelOption],
):
    prompt = RULE_PROPOSAL_PROMPT.format(
        rubric=rubric.text,
        matches="\n".join(matches),
    )

    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        model_options,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
    )

    return _parse_rules_output(outputs[0].first_text)


CLARIFICATION_QUESTIONS_PROMPT = """
A user specified a rubric for something they wanted to find in an agent run. We ran that rubric over a set of agent runs and found some matches.

Rubric:
{rubric}

Matches:
{matches}

Your task is to review the matches and generate thoughtful questions that would help the user clarify or refine their rubric. Focus on asking questions that clarify ambiguities in the current rubric that the user themselves might not have thought of.

Questions should be:
- Insightful
- Specific; the user should not be confused about what you mean
- Easy for a user to glance at and parse immediately
- Mutually exclusive: no two questions should ask the same thing

Be somewhat parsimonious; the user's time is valuable.

Return the questions in the following exact format:
<question>
...
</question>
...
"""


def _parse_questions_output(output_text: str | None) -> list[str] | None:
    """Parse questions from LLM output text containing <question>...</question> tags."""
    if output_text is None:
        return None
    else:
        # Pattern matches text between <question> and </question> tags
        pattern = r"<question>\n?(.*?)\n?</question>"
        matches = re.finditer(pattern, output_text, re.DOTALL)
        return [str(match.group(1).strip()) for match in matches]


async def generate_clarification_questions(
    rubric: Rubric,
    matches: list[str],
    model_options: list[ModelOption],
):
    """Generate clarifying questions to help the user refine their rubric."""
    prompt = CLARIFICATION_QUESTIONS_PROMPT.format(
        rubric=rubric.text,
        matches="\n".join(matches),
    )

    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        model_options,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
    )

    return _parse_questions_output(outputs[0].first_text)


RUBRIC_REFINEMENT_PROMPT = """
A user specified a rubric for something they wanted to find in an agent run. We generated clarifying questions to help refine the rubric, and the user provided answers.

Your task is to rewrite the rubric based on the user's answers to make it more precise and unambiguous. You may:
- Modify the high level description
- Add, remove, or modify inclusion rules
- Add, remove, or modify exclusion rules

Current rubric:
{rubric}

Questions and answers:
{qa_pairs}

Return the refined rubric in the following exact format:
<high_level_description>
...
</high_level_description>

<inclusion_rules>
<rule>
...
</rule>
<rule>
...
</rule>
</inclusion_rules>

<exclusion_rules>
<rule>
...
</rule>
<rule>
...
</rule>
</exclusion_rules>
"""


def _parse_refined_rubric_output(output_text: str | None) -> Rubric | None:
    """Parse refined rubric from LLM output text."""
    if output_text is None:
        return None

    # Extract high level description
    high_level_pattern = r"<high_level_description>\n?(.*?)\n?</high_level_description>"
    high_level_match = re.search(high_level_pattern, output_text, re.DOTALL)
    if not high_level_match:
        return None
    high_level_description = high_level_match.group(1).strip()

    # Extract inclusion rules
    inclusion_section_pattern = r"<inclusion_rules>\n?(.*?)\n?</inclusion_rules>"
    inclusion_section_match = re.search(inclusion_section_pattern, output_text, re.DOTALL)
    inclusion_rules = []
    if inclusion_section_match:
        inclusion_text = inclusion_section_match.group(1)
        rule_pattern = r"<rule>\n?(.*?)\n?</rule>"
        rule_matches = re.finditer(rule_pattern, inclusion_text, re.DOTALL)
        inclusion_rules = [match.group(1).strip() for match in rule_matches]

    # Extract exclusion rules
    exclusion_section_pattern = r"<exclusion_rules>\n?(.*?)\n?</exclusion_rules>"
    exclusion_section_match = re.search(exclusion_section_pattern, output_text, re.DOTALL)
    exclusion_rules = []
    if exclusion_section_match:
        exclusion_text = exclusion_section_match.group(1)
        rule_pattern = r"<rule>\n?(.*?)\n?</rule>"
        rule_matches = re.finditer(rule_pattern, exclusion_text, re.DOTALL)
        exclusion_rules = [match.group(1).strip() for match in rule_matches]

    return Rubric(
        high_level_description=high_level_description,
        inclusion_rules=inclusion_rules,
        exclusion_rules=exclusion_rules,
    )


async def refine_rubric_with_qa(
    rubric: Rubric,
    qa_pairs: list[tuple[str, str]],
    model_options: list[ModelOption],
) -> Rubric | None:
    """Refine a rubric based on question-answer pairs."""
    qa_text = "\n".join(f"Q: {q}\nA: {a}" for q, a in qa_pairs)

    prompt = RUBRIC_REFINEMENT_PROMPT.format(
        rubric=rubric.text,
        qa_pairs=qa_text,
    )

    outputs = await get_llm_completions_async(
        [
            [
                {
                    "role": "user",
                    "content": prompt,
                },
            ]
        ],
        model_options,
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
    )

    return _parse_refined_rubric_output(outputs[0].first_text)
