import enum
import json
from typing import Any, Protocol, cast
from uuid import uuid4

import jsonschema
from pydantic import BaseModel, Field, field_serializer

from docent._log_util import get_logger
from docent.data_models.agent_run import AgentRun
from docent.data_models.chat import ChatMessage
from docent.data_models.citation import parse_citations
from docent.data_models.remove_invalid_citation_ranges import remove_invalid_citation_ranges
from docent.data_models.transcript import TEXT_RANGE_CITE_INSTRUCTION
from docent_core._llm_util.data_models.llm_output import LLMOutput
from docent_core._llm_util.prod_llms import MessagesInput, get_llm_completions_async
from docent_core._llm_util.providers.preferences import PROVIDER_PREFERENCES, ModelOption

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

Reason through each part of the rubric carefully, then provide an output in JSON format.
Your output MUST adhere to the following schema:
{output_schema}
"""

DEFAULT_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string", "citations": True},
        "label": {"type": "string", "enum": ["match", "no match"]},
    },
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


class JudgeRunLabel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    agent_run_id: str
    rubric_id: str
    label: dict[str, Any]


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


class JudgeResultWithCitations(JudgeResult):
    @classmethod
    def from_judge_result(
        cls, result: JudgeResult, schema: dict[str, Any]
    ) -> "JudgeResultWithCitations":
        """Judge result must be validated against the schema before calling this function!"""

        def _parse_citations(output: Any, schema: dict[str, Any]) -> Any:
            if schema.get("type") == "string" and schema.get("citations"):  # type: ignore
                text, citations = parse_citations(output)
                return {
                    "text": text,
                    "citations": citations,
                }
            elif schema.get("type") == "object":
                properties: dict[str, Any] = schema.get("properties", {})
                return {key: _parse_citations(output[key], properties[key]) for key in properties}
            elif schema.get("type") == "array":
                item_schema: dict[str, Any] = schema.get("items", {})
                return [_parse_citations(item, item_schema) for item in output]
            else:
                return output

        data = result.model_dump()
        data["output"] = _parse_citations(data["output"], schema)
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
) -> dict[str, Any] | None:
    """Validate and filter citation text ranges in rubric results.

    Args:
        results: Raw results from LLM judge
        agent_run: Agent run containing transcript data for validation

    Returns:
        List of validated result strings with invalid citations removed
    """
    # Parse citations and validate them in one pass
    try:
        jsonschema.validate(output, output_schema)
    except jsonschema.ValidationError as e:
        logger.warning(f"Rubric output validation failed: {e}")
        return None

    def _validate(output: Any, schema: dict[str, Any]) -> Any:
        if schema.get("type") == "string" and schema.get("citations"):  # type: ignore
            validated_text = remove_invalid_citation_ranges(output, agent_run)
            if validated_text != output:
                logger.info(
                    f"Citation validation removed invalid text range from citation in judge result. "
                    f"Agent run ID: {agent_run.id}, "
                    f"Original text: {output}, "
                    f"Validated text: {validated_text}, "
                )
            return validated_text
        elif schema.get("type") == "object":
            properties: dict[str, Any] = schema.get("properties", {})
            return {key: _validate(output[key], properties[key]) for key in properties}
        elif schema.get("type") == "array":
            item_schema: dict[str, Any] = schema.get("items", {})
            return [_validate(item, item_schema) for item in output]
        else:
            return output

    return _validate(output, output_schema)


def _get_llm_callback(
    rubric: Rubric,
    agent_run_ids: list[str],
    agent_runs: list[AgentRun],
    callback: JudgeResultStreamingCallback,
    result_type: ResultType,
):
    async def _llm_callback(batch_index: int, llm_output: LLMOutput):
        text = llm_output.first_text
        output = json.loads(text) if text else None

        # Return nothing if the LLM call failed (hence None)
        if output is None:
            await callback(batch_index, None)
            return

        # Validate citations and clean up text
        validated_output = _validate_rubric_output(
            output, rubric.output_schema, agent_runs[batch_index]
        )
        if validated_output is None:
            await callback(batch_index, None)
            return

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

    return _llm_callback


def _get_prompt_resolver(rubric: Rubric, ar: AgentRun, prompt_template: str):
    def _prompt_resolver() -> list[ChatMessage | dict[str, Any]]:
        output_schema_text = json.dumps(rubric.output_schema, indent=2)

        prompt = prompt_template.format(
            rubric=rubric.rubric_text, agent_run=ar.to_text_new(), output_schema=output_schema_text
        )

        if _schema_requests_citations(rubric.output_schema):
            prompt += (
                "For strings which should contain citations (according to the schema) you must also follow these instructions: "
                + TEXT_RANGE_CITE_INSTRUCTION
                + RUBRIC_RESULT_EXPLANATION_INSTRUCTIONS
            )

        return [{"role": "user", "content": prompt}]

    return _prompt_resolver


async def evaluate_rubric(
    agent_runs: list[AgentRun],
    rubric: Rubric,
    api_key_overrides: dict[str, str] | None = None,
    callback: JudgeResultStreamingCallback | None = None,
    max_recall: bool = False,
):
    rubric_prompt = RUBRIC_MAX_RECALL_PROMPT if max_recall else RUBRIC_PROMPT
    result_type = ResultType.NEAR_MISS if max_recall else ResultType.DIRECT_RESULT

    prompt_resolvers: list[MessagesInput] = [
        _get_prompt_resolver(rubric, ar, rubric_prompt) for ar in agent_runs
    ]

    outputs = await get_llm_completions_async(
        prompt_resolvers,
        [rubric.judge_model],
        max_new_tokens=8192,
        timeout=180.0,
        use_cache=True,
        api_key_overrides=api_key_overrides,
        completion_callback=(
            _get_llm_callback(
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

    ans: list[dict[str, Any] | None] = [None] * len(prompt_resolvers)
    for i, output in enumerate(outputs):
        parsed_output = json.loads(output.first_text) if output.first_text else None
        if isinstance(parsed_output, dict):
            parsed_output = cast(dict[str, Any], parsed_output)
            ans[i] = _validate_rubric_output(parsed_output, rubric.output_schema, agent_runs[i])

    return ans


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


def validate_schema(schema: str | dict[str, Any]) -> tuple[bool, str | None]:
    """Validate whether a string or object is is valid JSON Schema."""
    try:
        if isinstance(schema, str):
            schema = json.loads(schema)
        jsonschema.validate(schema, DEFAULT_OUTPUT_SCHEMA)
        return True, None
    except (json.JSONDecodeError, jsonschema.ValidationError) as e:
        return False, f"Invalid JSON Schema: {e}"
