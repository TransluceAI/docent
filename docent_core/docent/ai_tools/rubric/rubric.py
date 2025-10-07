import enum
import json
from typing import Any, Callable, Protocol, cast
from uuid import uuid4

import jsonschema
from pydantic import BaseModel, Field, field_serializer

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import ChatMessage
from docent.data_models.citation import parse_citations
from docent.data_models.remove_invalid_citation_ranges import remove_invalid_citation_ranges
from docent.data_models.transcript import TEXT_RANGE_CITE_INSTRUCTION
from docent_core._llm_util.data_models.exceptions import ValidationFailedException
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import MessagesInput
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES, ModelOption
from docent_core.docent.ai_tools.rubric.forgiving_json import forgiving_json_loads
from docent_core.docent.services.llms import LLMService

logger = get_logger(__name__)

RUBRIC_RESULT_EXPLANATION_INSTRUCTIONS = """
- Outside of citations, do not refer to transcript numbers or block numbers.
- Be concise. Focus on the most important aspects of the agent's behavior.
- Outside of citations, avoid quoting or paraphrasing the transcript. Focus on describing high-level patterns.
"""

RUBRIC_PROMPT = """
Here is a rubric that we are using to judge transcripts of AI agent runs.

Rubric:
{rubric}

Agent run:
{agent_run}

Your response should convey your judgment of the agent run according to the criteria given in the rubric \
provided above. Your entire response must be a valid JSON string which can be parsed with python `json.loads` \
without any additional processing.
The JSON object you produce must adhere to the following schema:
{output_schema}

Double quotes (`"`) in the middle of a string in the JSON object must be escaped with a backslash.
"""

DEFAULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string", "citations": True},
        "label": {"type": "string", "enum": ["match", "no match"]},
    },
    # Require these properties to be present
    "required": ["label", "explanation"],
    # Allow additional properties though, as their presence is not breaking
}

DEFAULT_JUDGE_MODEL = PROVIDER_PREFERENCES.default_judge_models[0]


def _schema_requests_citations(schema: dict[str, Any]) -> bool:
    """Check if any field in the schema requests citations by having 'citations': 'true'."""

    def _check_field(field_schema: Any) -> bool:
        if isinstance(field_schema, dict):
            if field_schema.get("citations"):  # type: ignore
                return True
            for value in field_schema.values():  # type: ignore
                if isinstance(value, dict) and _check_field(value):
                    return True
                elif isinstance(value, list):
                    for item in value:  # type: ignore
                        if isinstance(item, dict) and _check_field(item):
                            return True
        return False

    return _check_field(schema)


class Rubric(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1
    rubric_text: str
    judge_model: ModelOption = DEFAULT_JUDGE_MODEL
    output_schema: dict[str, Any] = DEFAULT_OUTPUT_SCHEMA


class ResultType(enum.Enum):
    """Enum for the type of result that a judge result can have."""

    DIRECT_RESULT = "direct_result"
    NEAR_MISS = "near_miss"


class JudgeResult(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    rubric_id: str
    rubric_version: int
    output: dict[str, Any]

    value: str | None = None  # deprecated
    result_type: ResultType

    @field_serializer("result_type")
    def serialize_result_type(self, result_type: ResultType) -> str:
        return result_type.value


def _traverse_schema_and_transform(
    output: Any,
    schema: dict[str, Any],
    citation_string_handler: Callable[[str], Any],
) -> Any:
    """Recursively traverse output based on schema, applying citation_string_handler to citation strings."""
    if schema.get("type") == "string" and schema.get("citations"):  # type: ignore
        return citation_string_handler(output)
    elif schema.get("type") == "object":
        properties: dict[str, Any] = schema.get("properties", {})
        result: dict[str, Any] = {}
        for key in properties:
            if key in output:
                result[key] = _traverse_schema_and_transform(
                    output[key], properties[key], citation_string_handler
                )
        return result
    elif schema.get("type") == "array":
        item_schema: dict[str, Any] = schema.get("items", {})
        return [
            _traverse_schema_and_transform(item, item_schema, citation_string_handler)
            for item in output
        ]
    else:
        return output


class JudgeResultWithCitations(JudgeResult):
    @classmethod
    def from_judge_result(
        cls, result: JudgeResult, schema: dict[str, Any]
    ) -> "JudgeResultWithCitations":
        """Judge result must be validated against the schema before calling this function!"""

        def _parse_citation_string(output: str) -> dict[str, Any]:
            text, citations = parse_citations(output)
            return {"text": text, "citations": citations}

        data = result.model_dump()
        try:
            data["output"] = _traverse_schema_and_transform(
                data["output"], schema, _parse_citation_string
            )
        except Exception as e:
            logger.error(f"Failed to parse citations: {e}")
            logger.error(f"Output: {data['output']}")
            data["output"] = {"raw": data["output"]}
        return cls(**data)


class JudgeResultStreamingCallback(Protocol):
    """Supports batched streaming for cases where many search results are pre-computed.
    This avoids invoking the callback separately for each datapoint.
    """

    async def __call__(
        self,
        batch_index: int,
        judge_results: list[JudgeResult] | None,
    ) -> None: ...


def _validate_rubric_output(
    output: dict[str, Any], output_schema: dict[str, Any], agent_run: AgentRun
) -> dict[str, Any]:
    """Validate and filter citation text ranges in rubric results.

    Args:
        results: Raw results from LLM judge
        agent_run: Agent run containing transcript data for validation

    Returns:
        Validated result dict with invalid citations removed

    Raises:
        ValidationFailedException: If validation fails
    """

    def _validate_citation_string(text: str) -> str:
        validated_text = remove_invalid_citation_ranges(text, agent_run)
        if validated_text != text:
            logger.info(
                f"Citation validation removed invalid text range from citation in judge result. "
                f"Agent run ID: {agent_run.id}, "
                f"Original text: {text}, "
                f"Validated text: {validated_text}, "
            )
        return validated_text

    try:
        jsonschema.validate(output, output_schema)
    except jsonschema.ValidationError as e:
        raise ValidationFailedException(f"Schema validation failed: {e}", failed_output=str(output))

    try:
        return _traverse_schema_and_transform(output, output_schema, _validate_citation_string)
    except Exception as e:
        raise ValidationFailedException(
            f"Citation validation failed: {e}", failed_output=str(output)
        )


def _parse_and_validate_llm_output(
    llm_output: LLMOutput,
    output_schema: dict[str, Any],
    agent_run: AgentRun,
) -> dict[str, Any]:
    """Parse and validate LLM output for rubric evaluation.

    Args:
        llm_output: The LLM output to parse
        output_schema: The schema to validate against
        agent_run: Agent run for citation validation

    Returns:
        Validated output dict

    Raises:
        ValidationFailedException: If parsing or validation fails
    """
    if llm_output.first_text is None:
        raise ValidationFailedException("LLM output has no text", failed_output=None)

    try:
        output = forgiving_json_loads(llm_output.first_text)
    except json.JSONDecodeError as e:
        raise ValidationFailedException(
            f"Failed to parse JSON: {e}. Raw text: `{llm_output.first_text}`",
            failed_output=llm_output.first_text,
        )

    if not isinstance(output, dict):
        logger.error(f"Expected dict output, got {type(output)}")
        logger.error(f"LLM output: {llm_output.first_text}")
        raise ValidationFailedException(
            f"Expected dict output, got {type(output)}. Raw text: {llm_output.first_text}",
            failed_output=llm_output.first_text,
        )

    return _validate_rubric_output(cast(dict[str, Any], output), output_schema, agent_run)


def _get_validation_callback(
    rubric: Rubric,
    agent_runs: list[AgentRun],
):
    """Validation callback that throws ValidationFailedException if output is invalid."""

    async def _validation_callback(batch_index: int, llm_output: LLMOutput):
        _parse_and_validate_llm_output(llm_output, rubric.output_schema, agent_runs[batch_index])

    return _validation_callback


def _get_completion_callback(
    rubric: Rubric,
    agent_run_ids: list[str],
    agent_runs: list[AgentRun],
    callback: JudgeResultStreamingCallback,
    result_type: ResultType,
):
    """Completion callback that handles final results (success or error)."""

    async def _completion_callback(batch_index: int, llm_output: LLMOutput):
        if llm_output.did_error:
            await callback(batch_index, None)
        else:
            validated_output = _parse_and_validate_llm_output(
                llm_output, rubric.output_schema, agent_runs[batch_index]
            )
            await callback(
                batch_index,
                [
                    JudgeResult(
                        agent_run_id=agent_run_ids[batch_index],
                        rubric_id=rubric.id,
                        rubric_version=rubric.version,
                        result_type=result_type,
                        output=validated_output,
                    )
                ],
            )

    return _completion_callback


def construct_rubric_prompt(rubric: Rubric, agent_run: AgentRun, prompt_template: str) -> str:
    """Construct the full prompt text for rubric evaluation.

    This is the canonical implementation of prompt construction - use this function
    anywhere you need to construct a rubric evaluation prompt (including cost estimation).
    """
    output_schema_text = json.dumps(rubric.output_schema, indent=2)

    prompt = prompt_template.format(
        rubric=rubric.rubric_text,
        agent_run=agent_run.to_text_new(),
        output_schema=output_schema_text,
    )

    if _schema_requests_citations(rubric.output_schema):
        prompt += (
            "For strings which should contain citations (according to the schema) you must also follow these instructions: "
            + TEXT_RANGE_CITE_INSTRUCTION
            + RUBRIC_RESULT_EXPLANATION_INSTRUCTIONS
        )

    return prompt


def _get_prompt_resolver(rubric: Rubric, ar: AgentRun, prompt_template: str):
    def _prompt_resolver() -> list[ChatMessage | dict[str, Any]]:
        prompt = construct_rubric_prompt(rubric, ar, prompt_template)
        return [{"role": "user", "content": prompt}]

    return _prompt_resolver


async def evaluate_rubric(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    llm_svc: LLMService,
    callback: JudgeResultStreamingCallback | None = None,
    max_recall: bool = False,
):
    rubric_prompt = RUBRIC_MAX_RECALL_PROMPT if max_recall else RUBRIC_PROMPT
    result_type = ResultType.NEAR_MISS if max_recall else ResultType.DIRECT_RESULT

    prompt_resolvers: list[MessagesInput] = [
        _get_prompt_resolver(rubric, ar, rubric_prompt) for ar in agent_runs
    ]

    await llm_svc.get_completions(
        inputs=prompt_resolvers,
        model_options=[rubric.judge_model],
        max_new_tokens=16384,
        timeout=180.0,
        use_cache=True,
        validation_callback=_get_validation_callback(rubric, agent_runs),
        completion_callback=(
            _get_completion_callback(
                rubric,
                [ar.id for ar in agent_runs],
                agent_runs,
                callback,
                result_type,
            )
            if callback is not None
            else None
        ),
    )


RUBRIC_MAX_RECALL_PROMPT = """
We are currently engaging in a rubric refinement process where a user comes in with a vague idea of a behavior they are looking for in a dataset of AI agent run transcripts. Our job is to collaborate with the user to write out a concrete specification of what they are looking for - i.e., create and refine a rubric.

This is challenging because the user themselves may not fully understand what they are looking for. Therefore, while we elicit the user's intent, we also may show them information that will change *their* conception of the goal. The general principle is that we want to extract maximum feedback from the user while requiring minimal effort on their part.

Their initial rubric was:
{rubric}

Here is one specific agent run:
{agent_run}

Your job is to find concrete examples of behavior in this agent run that might be clarifying or illuminating for the user to see.
- Instances that you would consider to match the rubric are excellent choices to show, so you can confirm that the user agrees with your judgments.
- Instances that you are uncertain about but think could plausibly match are also excellent because the user may find it useful to clarify ambiguous examples and see things that they may not have thought of themselves.
- It is also possible that you may not see anything that could plausibly be conceived of as the rubric.

Your output MUST adhere to the following schema:
{output_schema}
"""
